"""OpenAPI / AsyncAPI loaders (JSON; YAML best-effort through yamlmini, else SpecError naming the
configured `api_spec.export_hint`).

API:
  SpecError
  load_spec(path, export_hint="") -> dict
  spec_kind(doc) -> "openapi" | "asyncapi" | None
  api_id(doc, path) -> str                           slug of info.title (fallback: file stem)
  openapi_operations(doc) -> [op]                    op = {method, path, operationId, summary, tags, deprecated,
                                                          parameters[], request_schema, responses{code: desc}}
  group_operations(ops) -> {group_slug: {"title", "ops": [...]}}   by tags[0] else first path segment
  asyncapi_channels(doc) -> [ch]                     ch = {channel, slug, description, operations[{action,
                                                          operationId, summary, message{name, fields[]}}]}
  detect_spec_files(tracked) -> {"openapi": [...], "asyncapi": [...]}
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Optional

from . import yamlmini
from .textnorm import slugify

__all__ = ["SpecError", "load_spec", "spec_kind", "api_id", "openapi_operations", "group_operations",
           "asyncapi_channels", "detect_spec_files", "HTTP_METHODS"]

HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
_OPENAPI_NAME = re.compile(r"(^|/)(openapi|swagger)[^/]*\.(json|ya?ml)$", re.I)
_ASYNCAPI_NAME = re.compile(r"(^|/)asyncapi[^/]*\.(json|ya?ml)$", re.I)


class SpecError(Exception):
    pass


def load_spec(path: Path, export_hint: str = "") -> dict:
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as e:
        raise SpecError(f"cannot read spec {p}: {e}")
    if p.suffix.lower() == ".json" or text.lstrip().startswith("{"):
        try:
            doc = json.loads(text)
        except ValueError as e:
            raise SpecError(f"{p}: invalid JSON: {e}")
    else:
        try:
            doc = yamlmini.loads(text)
        except yamlmini.YamlError as e:
            hint = f" Export it as JSON instead ({export_hint})." if export_hint else \
                " Export it as JSON (set api_spec.export_hint to the command)."
            raise SpecError(f"{p}: YAML subset parser failed at {e}.{hint}")
    if not isinstance(doc, dict):
        raise SpecError(f"{p}: spec must be an object")
    return doc


def spec_kind(doc: dict) -> Optional[str]:
    if "openapi" in doc or "swagger" in doc:
        return "openapi"
    if "asyncapi" in doc:
        return "asyncapi"
    return None


def api_id(doc: dict, path: str) -> str:
    title = (doc.get("info") or {}).get("title") if isinstance(doc.get("info"), dict) else None
    return slugify(title) if title else slugify(Path(path).stem)


def _deref(doc: dict, obj: Any, depth: int = 0) -> Any:
    if isinstance(obj, dict) and "$ref" in obj and isinstance(obj["$ref"], str) and depth < 8:
        ref = obj["$ref"]
        if ref.startswith("#/"):
            cur: Any = doc
            for part in ref[2:].split("/"):
                part = part.replace("~1", "/").replace("~0", "~")
                if isinstance(cur, dict) and part in cur:
                    cur = cur[part]
                else:
                    return {"$ref": ref}
            return _deref(doc, cur, depth + 1)
    return obj


def _schema_name(doc: dict, schema: Any) -> str:
    if isinstance(schema, dict):
        ref = schema.get("$ref")
        if isinstance(ref, str):
            return ref.rsplit("/", 1)[-1]
        if schema.get("type") == "array":
            return f"array of {_schema_name(doc, schema.get('items'))}"
        if "properties" in schema:
            return "object(" + ", ".join(sorted(schema["properties"].keys())[:8]) + ")"
        return str(schema.get("type") or "object")
    return "-"


def openapi_operations(doc: dict) -> list[dict]:
    ops: list[dict] = []
    paths = doc.get("paths") or {}
    if not isinstance(paths, dict):
        return ops
    for path in sorted(paths):
        item = _deref(doc, paths[path])
        if not isinstance(item, dict):
            continue
        shared_params = item.get("parameters") or []
        for method in HTTP_METHODS:
            op = item.get(method)
            if not isinstance(op, dict):
                continue
            params = []
            for prm in list(shared_params) + list(op.get("parameters") or []):
                prm = _deref(doc, prm)
                if isinstance(prm, dict):
                    params.append({"name": str(prm.get("name", "")), "in": str(prm.get("in", "")),
                                   "required": bool(prm.get("required", False))})
            req = None
            body = _deref(doc, op.get("requestBody"))
            if isinstance(body, dict):
                content = body.get("content") or {}
                for _, media in sorted(content.items()):
                    if isinstance(media, dict):
                        req = _schema_name(doc, media.get("schema"))
                        break
            responses = {}
            for code, resp in sorted((op.get("responses") or {}).items()):
                resp = _deref(doc, resp)
                if isinstance(resp, dict):
                    responses[str(code)] = str(resp.get("description") or "")
            tags = [str(t) for t in (op.get("tags") or []) if isinstance(t, (str, int))]
            ops.append({"method": method.upper(), "path": path, "operationId": str(op.get("operationId") or ""),
                        "summary": str(op.get("summary") or op.get("description") or "").strip().split("\n")[0],
                        "tags": tags, "deprecated": bool(op.get("deprecated", False)), "parameters": params,
                        "request_schema": req, "responses": responses})
    return ops


def group_operations(ops: Iterable[dict]) -> dict[str, dict]:
    groups: dict[str, dict] = {}
    for op in ops:
        if op.get("tags"):
            name = op["tags"][0]
        else:
            segs = [s for s in op["path"].split("/") if s and not s.startswith("{")]
            name = segs[0] if segs else "root"
            if name.startswith("v") and name[1:].isdigit() and len(segs) > 1:
                name = segs[1]
        slug = slugify(name)
        g = groups.setdefault(slug, {"title": name, "ops": []})
        g["ops"].append(op)
    for g in groups.values():
        g["ops"].sort(key=lambda o: (o["path"], o["method"]))
    return dict(sorted(groups.items()))


def _fields(doc: dict, payload: Any) -> list[str]:
    payload = _deref(doc, payload)
    if isinstance(payload, dict):
        props = payload.get("properties")
        if isinstance(props, dict):
            out = []
            for k in sorted(props):
                v = _deref(doc, props[k])
                t = v.get("type") if isinstance(v, dict) else None
                out.append(f"{k}: {t}" if t else str(k))
            return out
    return []


def asyncapi_channels(doc: dict) -> list[dict]:
    chans: list[dict] = []
    channels = doc.get("channels") or {}
    if not isinstance(channels, dict):
        return chans
    version = str(doc.get("asyncapi") or "")
    ops_v3: dict[str, list[dict]] = {}
    if version.startswith("3"):
        for op_id, op in sorted((doc.get("operations") or {}).items()):
            op = _deref(doc, op)
            if not isinstance(op, dict):
                continue
            ch_ref = op.get("channel") or {}
            key = ch_ref.get("$ref", "").rsplit("/", 1)[-1] if isinstance(ch_ref, dict) else str(ch_ref)
            msgs = []
            for m in op.get("messages") or []:
                m = _deref(doc, m)
                if isinstance(m, dict):
                    msgs.append({"name": str(m.get("name") or m.get("title") or ""), "fields": _fields(doc, m.get("payload"))})
            ops_v3.setdefault(key, []).append({"action": str(op.get("action") or ""), "operationId": op_id,
                                               "summary": str(op.get("summary") or op.get("description") or "").split("\n")[0],
                                               "message": msgs[0] if msgs else {"name": "", "fields": []}})
    for key in sorted(channels):
        ch = _deref(doc, channels[key])
        if not isinstance(ch, dict):
            continue
        address = str(ch.get("address") or key)
        entry = {"channel": address, "key": key, "slug": slugify(address), "description": str(ch.get("description") or "").strip(),
                 "operations": []}
        if version.startswith("3"):
            entry["operations"] = ops_v3.get(key, [])
            if not entry["operations"]:
                for mname, m in sorted((ch.get("messages") or {}).items()):
                    m = _deref(doc, m)
                    if isinstance(m, dict):
                        entry["operations"].append({"action": "message", "operationId": mname, "summary": str(m.get("summary") or ""),
                                                    "message": {"name": str(m.get("name") or mname), "fields": _fields(doc, m.get("payload"))}})
        else:
            for action in ("publish", "subscribe"):
                op = ch.get(action)
                if not isinstance(op, dict):
                    continue
                msg = _deref(doc, op.get("message") or {})
                if isinstance(msg, dict) and "oneOf" in msg:
                    msg = _deref(doc, (msg.get("oneOf") or [{}])[0])
                entry["operations"].append({"action": action, "operationId": str(op.get("operationId") or ""),
                                            "summary": str(op.get("summary") or op.get("description") or "").split("\n")[0],
                                            "message": {"name": str(msg.get("name") or msg.get("title") or "") if isinstance(msg, dict) else "",
                                                        "fields": _fields(doc, msg.get("payload")) if isinstance(msg, dict) else []}})
        chans.append(entry)
    return chans


def detect_spec_files(tracked: Iterable[str]) -> dict[str, list[str]]:
    out = {"openapi": [], "asyncapi": []}
    for f in sorted(tracked):
        if "node_modules/" in f or "/vendor/" in f or f.startswith("vendor/"):
            continue
        if _ASYNCAPI_NAME.search(f):
            out["asyncapi"].append(f)
        elif _OPENAPI_NAME.search(f):
            out["openapi"].append(f)
    return out

// Express front controller that proxies to the Python API.
import express, { Request, Response } from "express";
import { z } from "zod";

const app = express();
app.use(express.json());

export const OrderBody = z.object({ id: z.string(), customer_id: z.string() });

export function healthHandler(_req: Request, res: Response) {
  res.json({ ok: true });
}

export async function proxyOrder(req: Request, res: Response) {
  const parsed = OrderBody.safeParse(req.body);
  if (!parsed.success) {
    return res.status(400).json({ error: "invalid body" });
  }
  return res.status(202).json({ accepted: parsed.data.id });
}

app.get("/health", healthHandler);
app.post("/orders", proxyOrder);
app.get("/orders/:id", (req: Request, res: Response) => {
  res.json({ id: req.params.id });
});

export default app;

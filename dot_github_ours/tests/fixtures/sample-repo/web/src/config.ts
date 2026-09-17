export interface WebConfig {
  apiBase: string;
  port: number;
}

export const config: WebConfig = {
  apiBase: process.env.API_BASE ?? "http://localhost:8000",
  port: Number(process.env.PORT ?? 3000),
};

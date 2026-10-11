import "server-only";

import { headers } from "next/headers";

/** Ошибка api: HTTP-статус и detail из ответа FastAPI, например "WeakPassword". */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, detail: unknown) {
    super(`api ответил ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

type Options = { method?: "GET" | "POST" | "PUT"; body?: unknown; token?: string };

export async function apiFetch<T>(
  path: string,
  { method = "GET", body, token }: Options = {},
): Promise<T> {
  // читаем при каждом вызове: образ собирается один раз, адрес api приходит при запуске
  const base = process.env.API_URL;
  if (!base) throw new Error("API_URL не задан");

  // id запроса от Caddy: по нему логи api склеиваются с тем, что открыл человек
  const requestId = (await headers()).get("x-request-id");

  const res = await fetch(new URL(path, base), {
    method,
    headers: {
      ...(body !== undefined && { "Content-Type": "application/json" }),
      ...(token && { Authorization: `Bearer ${token}` }),
      ...(requestId && { "X-Request-ID": requestId }),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => null);
    throw new ApiError(res.status, data?.detail);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

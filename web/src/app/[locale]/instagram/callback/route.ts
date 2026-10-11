import { redirect } from "next/navigation";
import type { NextRequest } from "next/server";

import type { Account, ConnectResult } from "@/lib/accounts";
import { ApiError, apiFetch } from "@/lib/api";
import { getToken } from "@/lib/session";

// api отвечает кодом, страница аккаунтов показывает человеку текст
const RESULT: Record<number, ConnectResult> = { 400: "expired", 403: "forbidden", 502: "failed" };

/**
 * Возврат с экрана Instagram. Route handler, а не страница: он меняет данные
 * (подключает аккаунт), а рендер страницы побочных эффектов иметь не должен.
 */
export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams;
  // человек нажал «Отмена» на экране Instagram
  if (params.has("error")) redirect("/accounts?result=denied");

  // хвост #_ браузер не присылает, но Meta местами клеит его прямо в код
  const code = (params.get("code") ?? "").replace(/#_$/, "");
  const state = params.get("state") ?? "";
  let result: ConnectResult;
  let username = "";
  try {
    ({ username } = await apiFetch<Account>("/instagram/oauth/callback", {
      method: "POST",
      body: { code, state },
      token: await getToken(),
    }));
    result = "connected";
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    result = RESULT[e.status] ?? "failed";
    // сессия умерла, пока человек был на экране Instagram: войти и начать заново
    if (e.status === 401) redirect("/login");
  }
  // redirect бросает исключение, поэтому он вне try
  const query = new URLSearchParams({ result, ...(username && { username }) });
  redirect(`/accounts?${query}`);
}

import { ApiError, apiFetch } from "@/lib/api";
import { getToken } from "@/lib/session";
import type { UpdatePoll, UpdateStatus } from "@/lib/updates";
import { APP_VERSION } from "@/lib/version";

/**
 * Ход обновления для окна в меню. Постоянный адрес, а не server action: во время
 * обновления старая страница спрашивает уже новый сервер админки, а id server
 * actions меняются от сборки к сборке. Адрес у старой и новой версии один.
 *
 * version: версия сервера админки, что ответил. Сравнив её с той, до которой
 * обновлялись, окно понимает, что новая версия правда поднялась.
 */
export async function GET() {
  try {
    const status = await apiFetch<UpdateStatus>("/updates/status", { token: await getToken() });
    return Response.json({ ...status, version: APP_VERSION } satisfies UpdatePoll);
  } catch (e) {
    // нет сессии или не владелец: как ответил api
    if (e instanceof ApiError) return Response.json({ detail: e.detail }, { status: e.status });
    // api не отвечает: во время обновления он перезапускается, это шаг, а не ошибка
    const body: UpdatePoll = { phase: "restarting", version: APP_VERSION };
    return Response.json(body, { status: 503 });
  }
}

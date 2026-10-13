import "server-only";

import { cache } from "react";

import { ApiError, apiFetch } from "@/lib/api";
import { getToken } from "@/lib/session";

export type LocalizedText = { ru: string; en: string };

export type Release = {
  version: string;
  date: string;
  notes: LocalizedText;
  // что сделать до обновления: жёлтой плашкой
  important: LocalizedText | null;
  breaking: boolean;
  security: boolean;
};

// почему обновиться нельзя, хотя сайт ответил; имена совпадают с ключами в messages
export type UpdateBlocked = "dev" | "channel" | "min_from";

/** Что доступно этой установке, как отдаёт GET /updates. */
export type Updates = {
  current: string;
  channel: string;
  available: {
    // последняя версия канала, если она новее текущей
    latest: string | null;
    // все версии новее текущей до latest, новые сверху
    releases: Release[];
    blocked: UpdateBlocked | null;
    min_from: string | null;
  } | null;
  // объявление для всех установок с сайта
  message: LocalizedText | null;
  // сайт не ответил или файл кривой: available и message пустые
  error: "unreachable" | "invalid" | null;
};

/** Версии для окна обновления. Не владельцу: null, окно ему не показываем.
 * cache: кнопка обновления и строка версии в меню спрашивают одно, запрос один. */
export const getUpdates = cache(async (): Promise<Updates | null> => {
  try {
    return await apiFetch<Updates>("/updates", { token: await getToken() });
  } catch (e) {
    if (e instanceof ApiError && e.status === 403) return null;
    throw e;
  }
});

// фазы с доски хоста, как отдаёт GET /updates/status
export type UpdatePhase = "idle" | "queued" | "stuck" | "running" | "done" | "failed";

export type UpdateStatus = {
  phase: UpdatePhase;
  // строка с доски: «pull 0.1.2», «done 0.1.0 -> 0.1.2»
  step: string | null;
  at: string | null;
  // хвост лога, только у failed
  log: string[];
};

/** Ответ маршрута /api/update/status: статус и версия того сервера админки, что ответил.
 * restarting: api или админка перезапускаются, это шаг обновления, а не ошибка. */
export type UpdatePoll = (UpdateStatus | { phase: "restarting" }) & { version: string };

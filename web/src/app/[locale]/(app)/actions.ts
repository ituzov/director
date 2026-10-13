"use server";

import { cookies } from "next/headers";

import { ApiError, apiFetch } from "@/lib/api";
import { ACCOUNT_COOKIE } from "@/lib/current-account";
import { getToken } from "@/lib/session";
import type { UpdateStatus } from "@/lib/updates";

/** Запомнить аккаунт, выбранный в меню. Страница перерисуется с ним сама:
 * Next возвращает новый UI в ответе server action, который поменял cookie. */
export async function selectAccount(accountId: string) {
  (await cookies()).set(ACCOUNT_COOKIE, accountId, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60 * 24 * 365,
  });
}

// имена совпадают с ключами App.updates.errors в messages
export type UpdateRequestError = "Busy" | "NotAvailable" | "NotInstalled";

/** Попросить хост обновиться до version. Время просьбы по часам сервера: по нему
 * окно отличает новый итог на доске от итога прошлого обновления. */
export async function requestUpdate(
  version: string,
): Promise<{ at: string | null } | { error: UpdateRequestError }> {
  try {
    const status = await apiFetch<UpdateStatus>("/updates", {
      method: "POST",
      body: { version },
      token: await getToken(),
    });
    return { at: status.at };
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) return { error: e.detail as UpdateRequestError };
    throw e;
  }
}

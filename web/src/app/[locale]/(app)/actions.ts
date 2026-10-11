"use server";

import { cookies } from "next/headers";

import { ACCOUNT_COOKIE } from "@/lib/current-account";

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

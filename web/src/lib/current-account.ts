import "server-only";

import { cookies } from "next/headers";
import { cache } from "react";

import type { Account } from "@/lib/accounts";
import { apiFetch } from "@/lib/api";
import { getToken } from "@/lib/session";

/** Выбранный в меню аккаунт. Cookie, а не адрес: иначе каждую ссылку меню
 * пришлось бы дописывать параметром, и выбор терялся бы при переходе. */
export const ACCOUNT_COOKIE = "account";

/** Аккаунты, между которыми можно переключаться: отключённые не показываем. */
export const getSwitchableAccounts = cache(async (): Promise<Account[]> => {
  const accounts = await apiFetch<Account[]>("/instagram/accounts", { token: await getToken() });
  return accounts.filter((a) => a.status !== "disconnected");
});

/** Аккаунт, с которым работает админка: из cookie, а если там пусто или такого уже
 * нет, первый живой. null, если подключённых аккаунтов нет. */
export const getCurrentAccount = cache(async (): Promise<Account | null> => {
  const accounts = await getSwitchableAccounts();
  const chosen = (await cookies()).get(ACCOUNT_COOKIE)?.value;
  return (
    accounts.find((a) => a.id === chosen) ??
    accounts.find((a) => a.status === "active") ??
    accounts[0] ??
    null
  );
});

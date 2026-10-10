import "server-only";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { cache } from "react";

import { ApiError, apiFetch } from "@/lib/api";

export const SESSION_COOKIE = "director_session";

export type User = {
  id: string;
  email: string;
  role: "owner" | "member";
  can_connect_accounts: boolean;
};

export async function getToken(): Promise<string | undefined> {
  return (await cookies()).get(SESSION_COOKIE)?.value;
}

/** Только из server action: в рендере менять cookie нельзя. */
export async function setSessionCookie(token: string) {
  (await cookies()).set(SESSION_COOKIE, token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    // срок сессии решает api (скользящие 30 дней), cookie лишь не должна умереть раньше
    maxAge: 60 * 60 * 24 * 365,
  });
}

export async function deleteSessionCookie() {
  (await cookies()).delete(SESSION_COOKIE);
}

/** Кто вошёл. Нет сессии или она мертва: на вход. Один запрос к api на рендер. */
export const getCurrentUser = cache(async (): Promise<User> => {
  const token = await getToken();
  if (!token) redirect("/login");

  let user: User | null = null;
  try {
    user = await apiFetch<User>("/auth/me", { token });
  } catch (e) {
    if (!(e instanceof ApiError && e.status === 401)) throw e;
  }
  // redirect бросает исключение, поэтому он вне try
  if (!user) redirect("/login");
  return user;
});

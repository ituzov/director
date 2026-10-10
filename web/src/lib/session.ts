import "server-only";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { cache } from "react";

import { ApiError, apiFetch } from "@/lib/api";
import { SESSION_COOKIE } from "@/lib/session-cookie";

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

/** Кто вошёл, или null: нет cookie или api не признал сессию. Один запрос к api на рендер. */
export const findCurrentUser = cache(async (): Promise<User | null> => {
  const token = await getToken();
  if (!token) return null;
  try {
    return await apiFetch<User>("/auth/me", { token });
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) return null;
    throw e;
  }
});

/** Кто вошёл. Нет сессии или она мертва: на вход. */
export async function getCurrentUser(): Promise<User> {
  const user = await findCurrentUser();
  // redirect бросает исключение, поэтому он вне try
  if (!user) redirect("/login");
  return user;
}

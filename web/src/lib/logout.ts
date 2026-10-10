"use server";

import { redirect } from "next/navigation";

import { ApiError, apiFetch } from "@/lib/api";
import { deleteSessionCookie, getToken } from "@/lib/session";

/** Выход: сессию удаляет api, cookie удаляем сами. */
export async function logout() {
  const token = await getToken();
  if (token) {
    try {
      await apiFetch("/auth/logout", { method: "POST", token });
    } catch (e) {
      // сессия уже мертва: выходить из неё нечего, просто чистим cookie
      if (!(e instanceof ApiError && e.status === 401)) throw e;
    }
  }
  await deleteSessionCookie();
  redirect("/login");
}

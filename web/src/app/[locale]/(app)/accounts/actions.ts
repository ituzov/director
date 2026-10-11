"use server";

import { redirect } from "next/navigation";

import type { ConnectResult } from "@/lib/accounts";
import { ApiError, apiFetch } from "@/lib/api";
import { getToken } from "@/lib/session";

export type ConnectState = { error?: ConnectResult };

/** Увести человека на экран Instagram. Вернётся он на /instagram/callback. */
export async function connectInstagram(): Promise<ConnectState> {
  let url: string;
  try {
    ({ url } = await apiFetch<{ url: string }>("/instagram/oauth/url", {
      token: await getToken(),
    }));
  } catch (e) {
    // нет ключей Meta или адреса сервера: api говорит, чего не хватает
    if (e instanceof ApiError && e.status === 409) return { error: e.detail as ConnectResult };
    if (e instanceof ApiError && e.status === 403) return { error: "forbidden" };
    throw e;
  }
  // redirect бросает исключение, поэтому он вне try
  redirect(url);
}

"use server";

import { redirect } from "next/navigation";

import { ApiError, apiFetch } from "@/lib/api";
import { setSessionCookie } from "@/lib/session";

export type LoginState = { error?: "InvalidCredentials" };

export async function login(_prev: LoginState, form: FormData): Promise<LoginState> {
  const email = String(form.get("email") ?? "");
  const password = String(form.get("password") ?? "");

  let token: string;
  try {
    ({ token } = await apiFetch<{ token: string }>("/auth/login", {
      method: "POST",
      body: { email, password },
    }));
  } catch (e) {
    // 422 это кривой email: снаружи он неотличим от неверного пароля
    if (e instanceof ApiError && (e.status === 401 || e.status === 422)) {
      return { error: "InvalidCredentials" };
    }
    throw e;
  }
  await setSessionCookie(token);
  redirect("/");
}

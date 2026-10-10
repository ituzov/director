"use server";

import { redirect } from "next/navigation";

import { ApiError, apiFetch } from "@/lib/api";
import { setSessionCookie } from "@/lib/session";

// имена совпадают с detail из api, по ним форма берёт текст из messages
const API_ERRORS = [
  "SetupDisabled",
  "InvalidSetupToken",
  "OwnerAlreadyExists",
  "WeakPassword",
] as const;

type ApiSetupError = (typeof API_ERRORS)[number];
export type SetupError = ApiSetupError | "PasswordMismatch" | "InvalidEmail";
export type SetupState = { email: string; error?: SetupError };

function isApiSetupError(detail: unknown): detail is ApiSetupError {
  return API_ERRORS.includes(detail as ApiSetupError);
}

export async function setup(_prev: SetupState, form: FormData): Promise<SetupState> {
  const token = String(form.get("token") ?? "");
  const email = String(form.get("email") ?? "");
  const password = String(form.get("password") ?? "");

  // повтор пароля проверяем здесь: api про него не знает, это забота формы
  if (password !== String(form.get("confirm") ?? "")) {
    return { email, error: "PasswordMismatch" };
  }

  let sessionToken: string;
  try {
    ({ token: sessionToken } = await apiFetch<{ token: string }>("/setup", {
      method: "POST",
      body: { token, email, password },
    }));
  } catch (e) {
    if (e instanceof ApiError && isApiSetupError(e.detail)) return { email, error: e.detail };
    // 422 от pydantic, у него detail список: на деле это кривой email
    if (e instanceof ApiError && e.status === 422) return { email, error: "InvalidEmail" };
    throw e;
  }
  await setSessionCookie(sessionToken);
  redirect("/");
}

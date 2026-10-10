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
type SetupField = "token" | "email" | "password" | "confirm";

/** errors по полям формы, error общий: он не про конкретное поле. */
export type SetupState = {
  errors?: Partial<Record<SetupField, SetupError>>;
  error?: SetupError;
};

// к какому полю относится ошибка api; остальные показываются над кнопкой
const FIELD_OF: Partial<Record<ApiSetupError, SetupField>> = {
  InvalidSetupToken: "token",
  WeakPassword: "password",
};

function isApiSetupError(detail: unknown): detail is ApiSetupError {
  return API_ERRORS.includes(detail as ApiSetupError);
}

export async function setup(_prev: SetupState, form: FormData): Promise<SetupState> {
  const token = String(form.get("token") ?? "");
  const email = String(form.get("email") ?? "");
  const password = String(form.get("password") ?? "");

  // форма проверяет то же самое, но action можно вызвать и мимо неё
  if (password !== String(form.get("confirm") ?? "")) {
    return { errors: { confirm: "PasswordMismatch" } };
  }

  let sessionToken: string;
  try {
    ({ token: sessionToken } = await apiFetch<{ token: string }>("/setup", {
      method: "POST",
      body: { token, email, password },
    }));
  } catch (e) {
    if (e instanceof ApiError && isApiSetupError(e.detail)) {
      const field = FIELD_OF[e.detail];
      return field ? { errors: { [field]: e.detail } } : { error: e.detail };
    }
    // 422 от pydantic, у него detail список: на деле это кривой email
    if (e instanceof ApiError && e.status === 422) return { errors: { email: "InvalidEmail" } };
    throw e;
  }
  await setSessionCookie(sessionToken);
  redirect("/");
}

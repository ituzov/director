"use server";

import { refresh } from "next/cache";

import { ApiError, apiFetch } from "@/lib/api";
import { getToken } from "@/lib/session";

type MetaAppField = "app_id" | "app_secret";
// имена совпадают с ключами errors в messages
export type MetaAppError = "InvalidAppId" | "InvalidAppSecret" | "AppSecretRequired";
export type MetaAppState = { errors?: Partial<Record<MetaAppField, MetaAppError>> };

export async function saveMetaApp(_prev: MetaAppState, form: FormData): Promise<MetaAppState> {
  const secret = String(form.get("app_secret") ?? "").trim();
  try {
    await apiFetch("/instagram/app", {
      method: "PUT",
      // заблокированного поля нет в FormData: секрет не меняем
      body: { app_id: String(form.get("app_id") ?? ""), app_secret: secret || null },
      token: await getToken(),
    });
  } catch (e) {
    if (e instanceof ApiError && e.status === 422) return { errors: errorsOf(e.detail) };
    throw e;
  }
  // страница перерисуется с новыми данными: дата обновления, строки для Meta
  refresh();
  return {};
}

// AppSecretRequired от api или список ошибок pydantic с loc ["body", поле]
function errorsOf(detail: unknown): MetaAppState["errors"] {
  if (detail === "AppSecretRequired") return { app_secret: "AppSecretRequired" };
  const fields = Array.isArray(detail)
    ? detail.map((d: { loc?: unknown[] } | null) => d?.loc?.[1])
    : [];
  return {
    ...(fields.includes("app_id") && { app_id: "InvalidAppId" }),
    ...(fields.includes("app_secret") && { app_secret: "InvalidAppSecret" }),
  };
}

"use server";

import { refresh } from "next/cache";
import { redirect } from "next/navigation";

import type { AiConnection } from "@/lib/ai";
import { ApiError, apiFetch } from "@/lib/api";
import type { Assistant, AssistantConflict, TryResult } from "@/lib/assistants";
import { type MediaPage, mediaPage, type SelectedMedia, selectedMedia } from "@/lib/media";
import { getToken } from "@/lib/session";

type FormField =
  "name" | "media_ids" | "instruction" | "knowledge" | "daily_limit" | "connection_id" | "model";
// имена совпадают с ключами Assistants.form.errors в messages
export type FormError =
  | "required"
  | "tooLong"
  | "outOfRange"
  | "posts_required"
  | "posts_not_allowed"
  | "ConnectionMissing";
export type SaveState = {
  errors?: Partial<Record<FormField, FormError>>;
  conflict?: AssistantConflict;
  // не про поле: аккаунт отключён или ассистент уже в архиве
  failed?: "noAccount" | "AccountUnavailable" | "AssistantArchived";
};

/** Создать или сохранить ассистента. Ошибки api раскладываем по полям формы. */
export async function saveAssistant(_prev: SaveState, form: FormData): Promise<SaveState> {
  const id = text(form, "id");
  const body = bodyOf(form);
  try {
    if (id) {
      await apiFetch(`/assistants/${id}`, { method: "PUT", body, token: await getToken() });
    } else {
      // аккаунт из формы, а не из cookie: в другой вкладке могли выбрать другой
      const accountId = text(form, "account_id");
      if (!accountId) return { failed: "noAccount" };
      await apiFetch("/assistants", {
        method: "POST",
        body: { ...body, account_id: accountId },
        token: await getToken(),
      });
    }
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    if (e.detail === "ConnectionMissing") return { errors: { connection_id: "ConnectionMissing" } };
    if (e.status === 422) return { errors: errorsOf(e.detail) };
    const conflict = e.status === 409 ? conflictOf(e.body) : null;
    if (conflict) return { conflict };
    if (e.detail === "AccountUnavailable" || e.detail === "AssistantArchived") {
      return { failed: e.detail };
    }
    throw e;
  }
  // redirect бросает исключение, поэтому он вне try
  redirect("/assistants");
}

export async function setEnabled(id: string, enabled: boolean): Promise<void> {
  await apiFetch(`/assistants/${id}/enabled`, {
    method: "PUT",
    body: { enabled },
    token: await getToken(),
  });
  refresh();
}

export async function archive(id: string): Promise<void> {
  await apiFetch(`/assistants/${id}/archive`, { method: "POST", token: await getToken() });
  refresh();
}

/** Из архива. Место за это время занял другой: вернём, кто именно. */
export async function unarchive(id: string): Promise<{ conflict?: AssistantConflict }> {
  try {
    await apiFetch(`/assistants/${id}/unarchive`, { method: "POST", token: await getToken() });
  } catch (e) {
    const conflict = e instanceof ApiError && e.status === 409 ? conflictOf(e.body) : null;
    if (conflict) return { conflict };
    throw e;
  }
  refresh();
  return {};
}

/** Песочница по полям формы, даже несохранённым. FormData, а не объект: база и
 * коммент длинные, а Next в dev печатает аргументы серверных функций в терминал. */
export async function tryAssistant(form: FormData): Promise<TryResult> {
  const assistantId = text(form, "id");
  return apiFetch<TryResult>("/assistants/try", {
    method: "POST",
    body: {
      ...(assistantId && { assistant_id: assistantId }),
      mode: text(form, "mode"),
      instruction: text(form, "instruction"),
      knowledge: text(form, "knowledge"),
      connection_id: text(form, "connection_id"),
      model: text(form, "model"),
      comment: text(form, "try_comment"),
    },
    token: await getToken(),
  });
}

/** Подключения для выбора: только у владельца, участнику api отвечает 403. */
export async function loadConnections(): Promise<AiConnection[] | null> {
  try {
    return await apiFetch<AiConnection[]>("/ai/connections", { token: await getToken() });
  } catch (e) {
    if (e instanceof ApiError && e.status === 403) return null;
    throw e;
  }
}

export type ModelsResult = { models: { id: string; name: string | null }[]; error: string | null };

export async function loadModels(connectionId: string): Promise<ModelsResult> {
  return apiFetch<ModelsResult>(`/ai/connections/${connectionId}/models`, {
    token: await getToken(),
  });
}

/** Посты аккаунта для окна выбора: занятые другими ассистентами помечены. */
export async function loadMedia(
  accountId: string | null,
  assistantId: string | null,
  after: string | null,
): Promise<MediaPage> {
  return mediaPage(accountId, assistantId, after, (token) =>
    // без архивных: архив пост не держит
    apiFetch<Assistant[]>(`/assistants?${new URLSearchParams({ account_id: accountId ?? "" })}`, {
      token,
    }),
  );
}

export async function loadSelectedMedia(accountId: string, ids: string[]): Promise<SelectedMedia> {
  return selectedMedia(accountId, ids);
}

function text(form: FormData, key: string): string {
  return String(form.get(key) ?? "").trim();
}

function bodyOf(form: FormData) {
  const scope = text(form, "scope") === "posts" ? "posts" : "all";
  return {
    name: text(form, "name"),
    scope,
    media_ids: scope === "posts" ? form.getAll("media_ids").map(String) : [],
    mode: text(form, "mode"),
    instruction: text(form, "instruction"),
    knowledge: text(form, "knowledge"),
    daily_limit: Number(text(form, "daily_limit")),
    connection_id: text(form, "connection_id"),
    model: text(form, "model"),
  };
}

function conflictOf(body: unknown): AssistantConflict | null {
  return (body as { conflict?: AssistantConflict } | null)?.conflict ?? null;
}

type PydanticError = { loc?: unknown[]; msg?: string; type?: string };

// msg вида «Value error, posts_required»: правило формы целиком, относим к полю постов
const SCOPE_CODES = ["posts_required", "posts_not_allowed"] as const;

function errorsOf(detail: unknown): SaveState["errors"] {
  const errors: SaveState["errors"] = {};
  for (const item of Array.isArray(detail) ? (detail as PydanticError[]) : []) {
    const code = SCOPE_CODES.find((c) => item.msg?.includes(c));
    if (code) {
      errors.media_ids = code;
      continue;
    }
    const field = item.loc?.[1] as FormField | undefined;
    if (!field) continue;
    errors[field] = item.type?.includes("too_long")
      ? "tooLong"
      : item.type?.includes("greater") || item.type?.includes("less")
        ? "outOfRange"
        : "required";
  }
  return errors;
}

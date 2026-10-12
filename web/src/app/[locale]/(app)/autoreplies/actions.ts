"use server";

import { refresh } from "next/cache";
import { redirect } from "next/navigation";

import { ApiError, apiFetch } from "@/lib/api";
import type { Media } from "@/lib/accounts";
import type { Autoreply, AutoreplyConflict } from "@/lib/autoreplies";
import { getCurrentAccount } from "@/lib/current-account";
import { getToken } from "@/lib/session";

export type ActionResult = { conflict?: AutoreplyConflict };

export async function setEnabled(id: string, enabled: boolean): Promise<void> {
  await apiFetch(`/autoreplies/${id}/enabled`, {
    method: "PUT",
    body: { enabled },
    token: await getToken(),
  });
  refresh();
}

export async function archive(id: string): Promise<void> {
  await apiFetch(`/autoreplies/${id}/archive`, { method: "POST", token: await getToken() });
  refresh();
}

/** Из архива. Слово или пост за это время занял другой: вернём, кто именно. */
export async function unarchive(id: string): Promise<ActionResult> {
  try {
    await apiFetch(`/autoreplies/${id}/unarchive`, { method: "POST", token: await getToken() });
  } catch (e) {
    const conflict = e instanceof ApiError && e.status === 409 ? conflictOf(e.body) : null;
    if (conflict) return { conflict };
    throw e;
  }
  refresh();
  return {};
}

// пост занят частным автоответом: второй на него не повесить
export type TakenBy = { id: string; name: string; enabled: boolean };

export type MediaPage =
  | { items: Media[]; next: string | null; taken: Record<string, TakenBy> }
  // аккаунт отключён или токен истёк: повтор не поможет. Meta не ответила: поможет
  | { failed: "AccountUnavailable" | "MetaUnavailable" };

/** Страница постов из Meta и кто из них уже занят. Без аккаунта берём выбранный
 * в меню, как при создании; сам правимый автоответ пост не занимает. */
export async function loadMedia(
  accountId: string | null,
  autoreplyId: string | null,
  after: string | null,
): Promise<MediaPage> {
  const id = accountId ?? (await getCurrentAccount())?.id;
  if (!id) return { failed: "AccountUnavailable" };
  const token = await getToken();
  // 8 это два ряда в окне выбора, дальше «Показать ещё»
  const query = new URLSearchParams({ limit: "8", ...(after && { after }) });
  try {
    const [page, autoreplies] = await Promise.all([
      apiFetch<{ items: Media[]; next: string | null }>(
        `/instagram/accounts/${id}/media?${query}`,
        {
          token,
        },
      ),
      // без архивных: архив пост не держит
      apiFetch<Autoreply[]>(`/autoreplies?${new URLSearchParams({ account_id: id })}`, { token }),
    ]);
    const taken: Record<string, TakenBy> = {};
    for (const { id: ownerId, name, enabled, media_ids } of autoreplies) {
      if (ownerId === autoreplyId) continue;
      for (const mediaId of media_ids) taken[mediaId] = { id: ownerId, name, enabled };
    }
    return { ...page, taken };
  } catch (e) {
    if (
      e instanceof ApiError &&
      (e.detail === "AccountUnavailable" || e.detail === "MetaUnavailable")
    ) {
      return { failed: e.detail };
    }
    throw e;
  }
}

export type SelectedMedia =
  // missing: пост удалили или убрали в архив, а автоответ на нём ещё висит
  { items: Media[]; missing: string[] } | { failed: "AccountUnavailable" | "MetaUnavailable" };

/** Миниатюры уже выбранных постов автоответа, для ряда в форме. */
export async function loadSelectedMedia(accountId: string, ids: string[]): Promise<SelectedMedia> {
  const query = new URLSearchParams(ids.map((id) => ["ids", id]));
  try {
    return await apiFetch<{ items: Media[]; missing: string[] }>(
      `/instagram/accounts/${accountId}/media/selected?${query}`,
      { token: await getToken() },
    );
  } catch (e) {
    if (
      e instanceof ApiError &&
      (e.detail === "AccountUnavailable" || e.detail === "MetaUnavailable")
    ) {
      return { failed: e.detail };
    }
    throw e;
  }
}

function conflictOf(body: unknown): AutoreplyConflict | null {
  const conflict = (body as { conflict?: AutoreplyConflict } | null)?.conflict;
  return conflict ?? null;
}

export type FormFieldName =
  | "name"
  | "keywords"
  | "media_ids"
  | "intro_text"
  | "button_text"
  | "reply_text"
  | "not_following_text"
  | "comment_replies";

// наши коды из проверки формы в api: у каждого своё поле
const CODE_FIELD = {
  keyword_empty: "keywords",
  keyword_duplicate: "keywords",
  posts_required: "media_ids",
  posts_not_allowed: "media_ids",
  post_duplicate: "media_ids",
  not_following_text_required: "not_following_text",
} as const satisfies Record<string, FormFieldName>;

// коды ошибок: ключи AutoreplyForm.errors в messages
export type ErrorCode = keyof typeof CODE_FIELD | "required" | "tooLong" | "message_too_long";

export type SaveState = {
  errors?: Partial<Record<FormFieldName, ErrorCode>>;
  conflict?: AutoreplyConflict;
  // не про поле: аккаунта нет или автоответ уже в архиве
  failed?: "noAccount" | "AccountUnavailable" | "AutoreplyArchived";
};

/** Создать или сохранить автоответ. Ошибки api раскладываем по полям формы. */
export async function saveAutoreply(_prev: SaveState, form: FormData): Promise<SaveState> {
  const id = String(form.get("id") ?? "");
  const body = bodyOf(form);
  try {
    if (id) {
      await apiFetch(`/autoreplies/${id}`, { method: "PUT", body, token: await getToken() });
    } else {
      const account = await getCurrentAccount();
      if (!account) return { failed: "noAccount" };
      await apiFetch("/autoreplies", {
        method: "POST",
        body: { ...body, account_id: account.id },
        token: await getToken(),
      });
    }
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    if (e.status === 422) return { errors: errorsOf(e.detail) };
    const conflict = e.status === 409 ? conflictOf(e.body) : null;
    if (conflict) return { conflict };
    if (e.detail === "AccountUnavailable" || e.detail === "AutoreplyArchived") {
      return { failed: e.detail };
    }
    throw e;
  }
  // redirect бросает исключение, поэтому он вне try
  redirect("/autoreplies");
}

function bodyOf(form: FormData) {
  const text = (key: string) => String(form.get(key) ?? "").trim();
  const list = (key: string) => form.getAll(key).map(String);
  const scope = text("scope") === "posts" ? "posts" : "all";
  return {
    name: text("name"),
    scope,
    media_ids: scope === "posts" ? list("media_ids") : [],
    keywords: list("keywords"),
    intro_text: text("intro_text"),
    button_text: text("button_text"),
    reply_text: text("reply_text"),
    follow_gate: form.get("follow_gate") === "on",
    // текст храним, даже если проверка выключена: включат снова, и он на месте
    not_following_text: text("not_following_text") || null,
    comment_replies: list("comment_replies"),
    comment_reply_mode: text("comment_reply_mode") === "sequence" ? "sequence" : "random",
    enabled: form.get("enabled") !== "false",
  };
}

type PydanticError = { loc?: unknown[]; msg?: string; type?: string };

function errorsOf(detail: unknown): SaveState["errors"] {
  const errors: SaveState["errors"] = {};
  for (const item of Array.isArray(detail) ? (detail as PydanticError[]) : []) {
    // msg вида «Value error, keyword_empty»
    const code = (Object.keys(CODE_FIELD) as (keyof typeof CODE_FIELD)[]).find((c) =>
      item.msg?.includes(c),
    );
    if (code) {
      errors[CODE_FIELD[code]] = code;
      continue;
    }
    const field = item.loc?.[1] as FormFieldName | undefined;
    if (!field) continue;
    errors[field] = item.msg?.includes("message_too_long")
      ? "message_too_long"
      : item.type?.includes("too_long")
        ? "tooLong"
        : "required";
  }
  return errors;
}

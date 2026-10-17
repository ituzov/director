import "server-only";

import { ApiError, apiFetch } from "@/lib/api";
import type { AssistantHistory } from "@/lib/assistant-replies";
import type { History } from "@/lib/inbox";

/** Шаги выдачи по комментам страницы. Только для сервера: не server action,
 * браузер его сам не позовёт. Не ответило api: список без истории, а не ошибка. */
export async function loadHistory(
  accountId: string,
  commentIds: (string | null)[],
  token: string | undefined,
): Promise<History> {
  const ids = commentIds.filter((id): id is string => id !== null);
  if (ids.length === 0) return {};
  const query = new URLSearchParams({ account_id: accountId });
  for (const id of ids) query.append("comment_id", id);
  try {
    const { comments } = await apiFetch<{ comments: History }>(`/autoreplies/history?${query}`, {
      token,
    });
    return comments;
  } catch (error) {
    // в лог сервера Next: иначе сломанную ручку никто не заметит
    console.error("inbox.history_failed", error instanceof ApiError ? error.status : error);
    return {};
  }
}

/** Шаги ассистента по комментам страницы: решение и отправка частей ответа. */
export async function loadAssistantHistory(
  accountId: string,
  commentIds: string[],
  token: string | undefined,
): Promise<AssistantHistory> {
  if (commentIds.length === 0) return {};
  const query = new URLSearchParams({ account_id: accountId });
  for (const id of commentIds) query.append("comment_id", id);
  try {
    const { comments } = await apiFetch<{ comments: AssistantHistory }>(
      `/assistants/history?${query}`,
      { token },
    );
    return comments;
  } catch (error) {
    console.error(
      "inbox.assistant_history_failed",
      error instanceof ApiError ? error.status : error,
    );
    return {};
  }
}

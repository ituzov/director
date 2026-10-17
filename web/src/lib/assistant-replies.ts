import type { Tone } from "./deliveries";

/** Ответы ассистентов для вкладки «Ассистент» в журнале, как их отдаёт
 * GET /assistants/replies. */

export type AssistantReply = {
  id: string;
  comment_id: string;
  person_id: string;
  username: string | null;
  text: string;
  media_id: string;
  assistant_id: string;
  assistant_name: string;
  // null: ещё в очереди или у нейросети
  outcome: "answered" | "unsure" | "not_mine" | "limit" | "failed" | "expired" | "paused" | null;
  stage: "queued" | "thinking" | "sending" | "sent" | "send_failed" | "done";
  comment_reply: string | null;
  direct_reply: string | null;
  source: string | null;
  error_code: string | null;
  created_at: string;
  decided_at: string | null;
};

export type AssistantReplyPage = { items: AssistantReply[]; next: string | null };

/** Шаг ассистента по комменту из GET /assistants/history. */
export type AssistantStep = {
  step: string;
  at: string;
  assistant_id: string | null;
  // direct или comment у отправки
  part: string | null;
  reason: string | null;
};
export type AssistantHistory = Record<string, AssistantStep[]>;

// вкладки как в api (assistant/repository.TAB_FILTERS) и «все»
export const ASSISTANT_TABS = ["all", "answered", "unsure", "not_mine", "missed"] as const;
export type AssistantTab = (typeof ASSISTANT_TABS)[number];
export type AssistantCounts = Record<AssistantTab, number>;

/** Вкладка из адреса; незнакомая значит «все». */
export function assistantTabOf(value: string | string[] | undefined): AssistantTab {
  return ASSISTANT_TABS.find((tab) => tab === value) ?? "all";
}

export function assistantTabQuery(tab: AssistantTab): [string, string][] {
  return tab === "all" ? [] : [["tab", tab]];
}

/** Что с комментом сейчас, ключом текстов Inbox.assistant.state, и цвет точки.
 * Написанный, но не дошедший ответ это неудача, а не «ответил». */
// имена совпадают с ключами Inbox.assistant.state в messages
export type ReplyStateKey =
  | "queued"
  | "thinking"
  | "sending"
  | "sent"
  | "send_failed"
  | "unsure"
  | "not_mine"
  | "limit"
  | "failed"
  | "expired"
  | "paused";

export function replyState(r: Pick<AssistantReply, "outcome" | "stage">): {
  key: ReplyStateKey;
  tone: Tone;
} {
  if (r.stage === "send_failed") return { key: "send_failed", tone: "bad" };
  if (r.outcome === null)
    return { key: r.stage === "thinking" ? "thinking" : "queued", tone: "warn" };
  if (r.outcome === "answered") {
    return r.stage === "sent" ? { key: "sent", tone: "ok" } : { key: "sending", tone: "warn" };
  }
  if (r.outcome === "unsure") return { key: "unsure", tone: "warn" };
  if (r.outcome === "failed") return { key: "failed", tone: "bad" };
  return { key: r.outcome, tone: "muted" };
}

/** Запрос страницы ответов: аккаунт, вкладка и закладка. Один на первую страницу и
 * догрузку: иначе «Ещё» на вкладке тянуло бы строки всех вкладок. */
export function repliesQuery(
  accountId: string,
  tab: AssistantTab,
  limit: number,
  before?: string,
): URLSearchParams {
  return new URLSearchParams([
    ["account_id", accountId],
    ["limit", String(limit)],
    ...(before ? [["before", before] as [string, string]] : []),
    ...assistantTabQuery(tab),
  ]);
}

// коды, которые знает эта версия web: ai (сбой нейросети), наши и итоги отправки.
// Код Meta числом, незнакомое общим текстом с самим кодом
export const REPLY_ERRORS = [
  "key_rejected",
  "no_funds",
  "key_unreadable",
  "rate_limited",
  "timeout",
  "server",
  "bad_response",
  "bad_output",
  "step_limit",
  "not_configured",
  "model_missing",
  "cancelled",
  "stuck",
  "already_replied",
  "expired",
  "failed",
] as const;
export type ReplyError = (typeof REPLY_ERRORS)[number];

/** Ключ текста для кода ошибки: известный код, код Meta числом или «другое». */
export function errorKind(code: string): ReplyError | "meta" | "other" {
  if (/^\d+$/.test(code)) return "meta";
  return REPLY_ERRORS.find((c) => c === code) ?? "other";
}

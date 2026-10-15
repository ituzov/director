import type { Tone } from "./deliveries";
import type { InboxItem } from "./inbox";

/** Вкладки «Всех событий»: итог разбора, как его считает api
 * (GET /instagram/accounts/{id}/inbox/counts). */

export type ResultCounts = {
  taken: number;
  nobody: number;
  skipped: number;
  failed: number;
  // ещё не разобрано: ни в одну вкладку не входит, видно во «Всех»
  queued: number;
};

export const RESULT_TABS = ["all", "taken", "nobody", "skipped", "failed"] as const;
export type ResultTab = (typeof RESULT_TABS)[number];

/** Вкладка из адреса; незнакомая значит «все». По списку, а не `in`: тот видит прототип. */
export function resultOf(value: string | string[] | undefined): ResultTab {
  return RESULT_TABS.find((tab) => tab === value) ?? "all";
}

/** Сколько событий на вкладке: у «всех» сумма, включая неразобранные. */
export function resultCount(tab: ResultTab, counts: ResultCounts): number {
  if (tab !== "all") return counts[tab];
  return Object.values(counts).reduce((sum, n) => sum + n, 0);
}

/** Параметр запроса ленты для вкладки. */
export function resultQuery(tab: ResultTab): [string, string][] {
  return tab === "all" ? [] : [["result", tab]];
}

// причины пропуска с подписью; остальные общим словом
const SKIP_REASONS = ["own_comment", "unknown_account", "account_inactive", "bad_payload"] as const;
type SkipReason = (typeof SKIP_REASONS)[number] | "other";

function skipReason(reason: string | null): SkipReason {
  return SKIP_REASONS.find((r) => r === reason) ?? "other";
}

type Params = Record<string, string>;
export type ResultKey =
  | "outcome.queued"
  | "outcome.failed"
  | `outcome.skipped.${SkipReason}`
  | "outcome.autoreply"
  | "outcome.autoreplies"
  | "outcome.buttonNoDelivery"
  | "outcome.handled"
  | "outcome.noMatch"
  | "outcome.foreignButton"
  | "outcome.noReply";
export type WhyKey =
  | "why.queued"
  | "why.retrying"
  | "why.failed"
  | `why.skipped.${SkipReason}`
  | "why.takenComment"
  | "why.takenPress"
  | "why.taken"
  | "why.takenNoName"
  | "why.buttonNoDelivery"
  | "why.handled"
  | "why.noMatch"
  | "why.foreignButton"
  | "why.noReply";

export type Explained = {
  result: { key: ResultKey; params?: Params; tone: Tone };
  why: { key: WhyKey; params?: Params };
};

/** Чем кончился разбор события и почему, ключами текстов Inbox. Только сам разбор:
 * что было с выдачей дальше, рассказывают «Выдачи». name: название автоответа по
 * handled_ref; нет, если автоответ не определить или его нет в списке. */
export function explain(item: InboxItem, name: string | undefined): Explained {
  if (item.outcome === null) {
    // reason у неразобранного: разбор падал, событие ждёт повтора
    const why: Explained["why"] = item.reason
      ? { key: "why.retrying", params: { reason: item.reason } }
      : { key: "why.queued" };
    return { result: { key: "outcome.queued", tone: "warn" }, why };
  }
  if (item.outcome === "failed") {
    return {
      result: { key: "outcome.failed", tone: "bad" },
      why: { key: "why.failed", params: { reason: item.reason ?? "?" } },
    };
  }
  if (item.outcome === "skipped") {
    const reason = skipReason(item.reason);
    return {
      result: { key: `outcome.skipped.${reason}`, tone: "muted" },
      why: { key: `why.skipped.${reason}` },
    };
  }
  if (item.handled_by === "autoreplies") {
    // кнопка наша, но выдачи нет: нажал не тот, кому отправили, или кнопка битая
    if (item.kind === "postback" && !item.handled_ref) {
      return {
        result: { key: "outcome.buttonNoDelivery", tone: "muted" },
        why: { key: "why.buttonNoDelivery" },
      };
    }
    const result: Explained["result"] = name
      ? { key: "outcome.autoreply", params: { name }, tone: "ok" }
      : { key: "outcome.autoreplies", tone: "ok" };
    const why: Explained["why"] = !name
      ? { key: "why.takenNoName" }
      : item.kind === "comment"
        ? { key: "why.takenComment", params: { name } }
        : item.kind === "postback"
          ? { key: "why.takenPress", params: { name } }
          : { key: "why.taken", params: { name } };
    return { result, why };
  }
  if (item.handled_by) {
    return { result: { key: "outcome.handled", tone: "ok" }, why: { key: "why.handled" } };
  }
  // разобрано, но никто не взял
  if (item.kind === "comment") {
    return { result: { key: "outcome.noMatch", tone: "muted" }, why: { key: "why.noMatch" } };
  }
  if (item.kind === "postback") {
    return {
      result: { key: "outcome.foreignButton", tone: "muted" },
      why: { key: "why.foreignButton" },
    };
  }
  return { result: { key: "outcome.noReply", tone: "muted" }, why: { key: "why.noReply" } };
}

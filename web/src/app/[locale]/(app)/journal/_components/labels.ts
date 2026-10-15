import type { useFormatter, useTranslations } from "next-intl";

import type { InboxItem, Step } from "@/lib/inbox";

export type T = ReturnType<typeof useTranslations<"Inbox">>;
type Format = ReturnType<typeof useFormatter>;

/** Сегодня часы, раньше дата. */
export function shortTime(at: Date, now: number, format: Format): string {
  const today = new Date(now).toDateString() === at.toDateString();
  return format.dateTime(
    at,
    today ? { hour: "2-digit", minute: "2-digit" } : { day: "numeric", month: "short" },
  );
}

/** Полное время для подсказки при наведении. */
export function longTime(at: Date, format: Format): string {
  return format.dateTime(at, { dateStyle: "long", timeStyle: "medium" });
}

export function who(item: Pick<InboxItem, "username" | "person_id">, t: T): string {
  if (item.username) return `@${item.username}`;
  // ника нет: человек не писал комментов этому аккаунту, видно только хвост id
  if (item.person_id) return `…${item.person_id.slice(-4)}`;
  return t("unknownPerson");
}

export function stepText(step: Step, t: T): string {
  if (step.step === "matched") {
    return step.keyword ? t("step.matched", { keyword: step.keyword }) : t("step.matchedNoWord");
  }
  // following не пишем: проверили и выдали, это обычный случай
  if (step.step === "delivered" && step.follow === "unknown") return t("step.deliveredUnchecked");
  // api добавил шаг, которого web ещё не знает: общий текст, а не сырой ключ
  const key = `step.${step.step}` as const;
  return t.has(key) ? t(key) : t("step.other");
}

/** Почему не ушло. reason бывает кодом Meta, нашей причиной или именем исключения. */
export function failureText(step: Step, t: T): string {
  if (step.outcome === "expired") return t("failure.expired");
  if (step.reason && /^\d+$/.test(step.reason)) return t("failure.meta", { code: step.reason });
  if (step.reason === "account_inactive") return t("failure.account_inactive");
  return t("failure.other");
}

// ok: получил; warn: ждём человека; bad: не ушло; muted: идёт своим ходом

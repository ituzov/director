"use client";

import { Bot, ChevronRight } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { useId, useState } from "react";

import { Link } from "@/i18n/navigation";
import {
  type AssistantHistory,
  type AssistantReply,
  type AssistantReplyPage,
  type AssistantStep,
  type AssistantTab,
  errorKind,
  replyState,
} from "@/lib/assistant-replies";
import { cn } from "@/lib/utils";

import { loadAssistantReplies } from "../actions";
import { longTime, shortTime, who } from "./labels";
import { MoreButton } from "./more-button";
import { useFeed } from "./use-feed";

// колонки как у «Автоответов»: человек, ассистент, итог, когда, стрелка
const ROW =
  "grid grid-cols-[minmax(0,1fr)_auto] gap-x-4 gap-y-1 px-4 md:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_minmax(0,1fr)_4.5rem_1rem] md:items-center";

const DOT = {
  ok: "bg-success-foreground",
  warn: "bg-warning-foreground",
  bad: "bg-destructive",
  muted: "bg-muted-foreground/50",
} as const;

/** Что ассистенты сделали с комментами: кто спросил, кто отвечал, чем кончилось. */
export function AssistantTable({
  accountId,
  tab,
  initial,
  history: initialHistory,
  now,
}: {
  accountId: string;
  tab: AssistantTab;
  initial: AssistantReplyPage;
  history: AssistantHistory;
  // момент запроса страницы: «сегодня» в браузере совпадёт с серверным
  now: number;
}) {
  const t = useTranslations("Inbox.assistant");
  const { items, history, next, failed, pending, more } = useFeed(
    initial,
    initialHistory,
    (before) => loadAssistantReplies(accountId, before, tab),
  );

  if (items.length === 0) {
    return (
      <div className="grid justify-items-center gap-2 py-10 text-center text-sm">
        <Bot className="size-8 text-muted-foreground" />
        <p className="font-medium">{t(tab === "all" ? "empty" : "emptyTab")}</p>
        {tab === "all" && (
          <p className="max-w-md text-muted-foreground">
            {t.rich("emptyHint", {
              link: (chunks) => (
                <Link href="/assistants" className="text-foreground underline">
                  {chunks}
                </Link>
              ),
            })}
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="grid gap-4">
      <div className="rounded-lg border bg-card">
        <div
          aria-hidden
          className={cn(ROW, "hidden h-9 border-b text-xs text-muted-foreground md:grid")}
        >
          <span>{t("columns.person")}</span>
          <span>{t("columns.assistant")}</span>
          <span>{t("columns.result")}</span>
          <span className="text-right">{t("columns.when")}</span>
          <span />
        </div>
        <ul className="divide-y">
          {items.map((r) => (
            <Row key={r.id} reply={r} steps={history[r.comment_id] ?? []} now={now} />
          ))}
        </ul>
      </div>
      {next && <MoreButton pending={pending} failed={failed} onClick={more} />}
    </div>
  );
}

function Row({
  reply: r,
  steps,
  now,
}: {
  reply: AssistantReply;
  steps: AssistantStep[];
  now: number;
}) {
  const t = useTranslations("Inbox.assistant");
  const tInbox = useTranslations("Inbox");
  const format = useFormatter();
  const [open, setOpen] = useState(false);
  const detailsId = useId();
  const at = new Date(r.created_at);
  const state = replyState(r);

  return (
    <li>
      {/* кнопка раскрытия растянута на всю строку, ссылка на ассистента поверх неё */}
      <div
        className={cn(
          ROW,
          "relative py-3 text-sm hover:bg-muted/50 has-[button:focus-visible]:outline-2 has-[button:focus-visible]:-outline-offset-2 has-[button:focus-visible]:outline-ring",
        )}
      >
        <button
          type="button"
          aria-expanded={open}
          aria-controls={detailsId}
          onClick={() => setOpen((v) => !v)}
          className="min-w-0 text-left outline-none after:absolute after:inset-0"
        >
          <span className="block truncate font-medium">{who(r, tInbox)}</span>
          {r.text && (
            <span className="block truncate text-muted-foreground" title={r.text}>
              «{r.text}»
            </span>
          )}
        </button>
        <time
          dateTime={r.created_at}
          title={longTime(at, format)}
          className="col-start-2 row-start-1 self-start text-right font-mono text-xs text-muted-foreground tabular-nums md:col-start-4 md:self-center"
        >
          {shortTime(at, now, format)}
        </time>
        <span className="col-span-2 flex min-w-0 items-center text-muted-foreground md:col-span-1 md:col-start-2 md:row-start-1">
          <span className="shrink-0 md:hidden">{t("columns.assistant")}:&nbsp;</span>
          <Link
            href={`/assistants/${r.assistant_id}`}
            className="relative z-10 -my-2.5 inline-flex min-h-10 max-w-full min-w-0 items-center hover:text-foreground hover:underline md:-my-2 md:min-h-9"
          >
            <span className="truncate">{r.assistant_name}</span>
          </Link>
        </span>
        <span className="col-span-2 grid min-w-0 grid-cols-[0.375rem_minmax(0,1fr)] items-center gap-x-2 md:col-span-1 md:col-start-3 md:row-start-1">
          <span aria-hidden className={cn("size-1.5 rounded-full", DOT[state.tone])} />
          <span className={cn("truncate", state.tone === "bad" && "text-destructive")}>
            {t(`state.${state.key}`)}
          </span>
        </span>
        <ChevronRight
          aria-hidden
          className={cn(
            "hidden size-4 text-muted-foreground transition-transform md:col-start-5 md:row-start-1 md:block",
            open && "rotate-90",
          )}
        />
      </div>
      <div id={detailsId} hidden={!open} className="grid gap-3 px-4 pb-4 text-sm">
        {r.comment_reply && <Quote label={t("inComment")} text={r.comment_reply} />}
        {r.direct_reply && <Quote label={t("inDirect")} text={r.direct_reply} />}
        {r.source && (
          <p className="text-xs text-muted-foreground">{t("source", { source: r.source })}</p>
        )}
        {r.error_code && <p className="text-xs text-destructive">{errorText(r.error_code, t)}</p>}
        {steps.length > 0 && (
          <ol className="grid grid-cols-[3.5rem_minmax(0,1fr)] gap-x-3 gap-y-1.5">
            {steps.map((step, i) => (
              <li key={i} className="col-span-full grid grid-cols-subgrid">
                <time
                  dateTime={step.at}
                  title={longTime(new Date(step.at), format)}
                  className="text-muted-foreground tabular-nums"
                >
                  {format.dateTime(new Date(step.at), { hour: "2-digit", minute: "2-digit" })}
                </time>
                <span className={cn(step.step === "send_failed" && "text-destructive")}>
                  {stepText(step, t)}
                </span>
              </li>
            ))}
          </ol>
        )}
        {/* в очереди или у нейросети: показать пока нечего */}
        {!r.comment_reply && !r.direct_reply && !r.error_code && steps.length === 0 && (
          <p className="text-muted-foreground">{t("nothingYet")}</p>
        )}
      </div>
    </li>
  );
}

type T = ReturnType<typeof useTranslations<"Inbox.assistant">>;

// шаги, которые знает эта версия web; новый из api: общий текст, а не сырой ключ
const STEPS = ["answered", "unsure", "not_mine", "limit", "failed", "expired", "paused"] as const;

function stepText(step: AssistantStep, t: T): string {
  if (step.step === "sent" || step.step === "send_failed") {
    const part = step.part === "comment" ? "comment" : "direct";
    const text = t(`steps.${step.step}.${part}`);
    // причины может не быть (окно ответа закрылось у самой очереди): без пустого хвоста
    return step.step === "send_failed" && step.reason
      ? `${text}: ${errorText(step.reason, t)}`
      : text;
  }
  const known = STEPS.find((s) => s === step.step);
  return known ? t(`steps.${known}`) : t("steps.other");
}

/** Код ошибки словами: ai, наши и итоги отправки; код Meta числом. */
function errorText(code: string, t: T): string {
  const kind = errorKind(code);
  if (kind === "meta" || kind === "other") return t(`errors.${kind}`, { code });
  return t(`errors.${kind}`);
}

function Quote({ label, text }: { label: string; text: string }) {
  return (
    <div className="grid gap-1">
      <span className="text-xs text-muted-foreground">{label}</span>
      <p className="rounded-lg bg-muted px-3 py-2 whitespace-pre-wrap">{text}</p>
    </div>
  );
}

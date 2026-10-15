"use client";

import {
  CircleAlert,
  CircleCheck,
  CircleDashed,
  CircleMinus,
  Clock,
  Inbox,
  Mail,
  MessageCircle,
  MousePointerClick,
} from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { useId, useState } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { Link } from "@/i18n/navigation";
import {
  type History,
  type InboxItem,
  type InboxPage,
  type Step,
  summary,
  type Summary,
} from "@/lib/inbox";
import { cn } from "@/lib/utils";

import { loadInbox } from "../actions";
import { longTime, shortTime, type T, TONE_TEXT, toneOf, type Tone, who } from "./labels";
import { MoreButton } from "./more-button";
import { Steps } from "./steps";
import { SummaryToggle, type Toggle } from "./summary-toggle";
import { useFeed } from "./use-feed";

type Props = {
  accountId: string;
  initial: InboxPage;
  // шаги выдачи по id коммента: что было после того, как автоответ взял коммент
  history: History;
  // название автоответа по id: handled_ref у событий, которые взяли автоответы
  names: Record<string, string>;
  // момент запроса страницы: «сегодня» в браузере совпадёт с серверным
  now: number;
};

const KIND_ICON = { comment: MessageCircle, postback: MousePointerClick, message: Mail } as const;

// причины пропуска и вложения, у которых есть подпись; остальные общим словом
const SKIP_REASONS = ["own_comment", "unknown_account", "account_inactive", "bad_payload"] as const;
const ATTACHMENTS = ["ig_reel", "image", "video", "audio", "share", "story_mention"] as const;

function oneOf<T extends string>(list: readonly T[], value: string | null): value is T {
  return value !== null && (list as readonly string[]).includes(value);
}

export function InboxList({ accountId, initial, history: initialHistory, names, now }: Props) {
  const t = useTranslations("Inbox");
  const { items, history, next, failed, pending, more } = useFeed(
    initial,
    initialHistory,
    (before) => loadInbox(accountId, before),
  );

  if (items.length === 0) {
    return (
      // как пустые списки у Dokploy: крупная иконка по центру, под ней подсказка
      <div className="grid justify-items-center gap-2 py-10 text-center text-sm">
        <Inbox className="size-8 text-muted-foreground" />
        <p className="font-medium">{t("empty")}</p>
        <p className="max-w-md text-muted-foreground">
          {t.rich("emptyHint", {
            link: (chunks) => (
              <Link href="/settings/meta" className="text-foreground underline">
                {chunks}
              </Link>
            ),
          })}
        </p>
      </div>
    );
  }

  return (
    <div className="grid gap-4">
      <ul className="divide-y rounded-lg border">
        {items.map((item) => (
          <Row
            key={item.id}
            item={item}
            steps={(item.comment_id && history[item.comment_id]) || []}
            names={names}
            now={now}
          />
        ))}
      </ul>
      {next && <MoreButton pending={pending} failed={failed} onClick={more} />}
    </div>
  );
}

function Row({
  item,
  steps,
  names,
  now,
}: {
  item: InboxItem;
  steps: Step[];
  names: Props["names"];
  now: number;
}) {
  const t = useTranslations("Inbox");
  const format = useFormatter();
  const [open, setOpen] = useState(false);
  const stepsId = useId();
  const Icon = KIND_ICON[item.kind];
  const at = new Date(item.received_at);

  return (
    // телефон: время и кто сверху, итог под текстом; шире: всё в одну строку
    <li className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 px-4 py-3 text-sm md:grid-cols-[4.5rem_minmax(0,1fr)_auto] md:items-center">
      <time
        dateTime={item.received_at}
        title={longTime(at, format)}
        className="text-muted-foreground tabular-nums"
      >
        {shortTime(at, now, format)}
      </time>
      <div className="flex min-w-0 items-center gap-2">
        <Icon
          className="size-4 shrink-0 text-muted-foreground"
          aria-label={t(`kind.${item.kind}`)}
        />
        <span className="shrink-0 font-medium">{who(item, t)}</span>
        <span className="truncate text-muted-foreground" title={what(item, t) ?? undefined}>
          {what(item, t)}
        </span>
      </div>
      <div className="col-span-2 md:col-span-1 md:justify-self-end">
        <Outcome
          item={item}
          names={names}
          steps={steps}
          toggle={{ open, controls: stepsId, onClick: () => setOpen((v) => !v) }}
        />
      </div>
      {steps.length > 0 && (
        // сетка строки (subgrid): время шага ровно под временем коммента
        <Steps
          id={stepsId}
          open={open}
          steps={steps}
          now={now}
          className="col-span-full grid-cols-subgrid pt-2"
        />
      )}
    </li>
  );
}

function what(item: InboxItem, t: T): string | null {
  if (item.kind === "postback") return item.text ? t("pressed", { title: item.text }) : null;
  if (item.text) return item.kind === "comment" ? `«${item.text}»` : item.text;
  if (item.attachment) {
    return t(`attachment.${oneOf(ATTACHMENTS, item.attachment) ? item.attachment : "other"}`);
  }
  return null;
}

/** Что Директор сделал с событием, человеческим языком. */
function Outcome({
  item,
  names,
  steps,
  toggle,
}: {
  item: InboxItem;
  names: Props["names"];
  steps: Step[];
  toggle: Toggle;
}) {
  const t = useTranslations("Inbox.outcome");

  if (item.outcome === null) return <Status tone="muted" icon={CircleDashed} text={t("queued")} />;
  if (item.outcome === "failed") return <Status tone="bad" icon={CircleAlert} text={t("failed")} />;
  if (item.outcome === "skipped") {
    const reason = oneOf(SKIP_REASONS, item.reason) ? item.reason : "other";
    return <Status tone="muted" icon={CircleMinus} text={t(`skipped.${reason}`)} />;
  }
  if (item.handled_by === "autoreplies") {
    const name = item.handled_ref ? names[item.handled_ref] : undefined;
    const result = summary(steps);
    if (result) return <Delivery item={item} name={name} result={result} toggle={toggle} />;
    if (!name) return <Status tone="ok" icon={CircleCheck} text={t("autoreplies")} />;
    return (
      <Link href={`/autoreplies/${item.handled_ref}`} className="hover:underline">
        <Status tone="ok" icon={CircleCheck} text={t("autoreply", { name })} />
      </Link>
    );
  }
  // разобрано, но никто не взял
  const text =
    item.kind === "comment"
      ? t("noMatch")
      : item.kind === "postback"
        ? t("foreignButton")
        : t("noReply");
  return <Status tone="muted" icon={CircleMinus} text={text} />;
}

/** Автоответ и чем кончилась выдача; по итогу раскрываются шаги. */
function Delivery({
  item,
  name,
  result,
  toggle,
}: {
  item: InboxItem;
  name: string | undefined;
  result: Summary;
  toggle: Toggle;
}) {
  const t = useTranslations("Inbox");
  const tone = toneOf(result);
  const Icon =
    tone === "ok"
      ? CircleCheck
      : tone === "bad"
        ? CircleAlert
        : result === "repeat_comment"
          ? CircleMinus
          : Clock;

  return (
    <span className={cn("inline-flex flex-wrap items-center gap-x-1.5", TONE_TEXT[tone])}>
      <Icon className="size-4 shrink-0" />
      {name ? (
        <Link href={`/autoreplies/${item.handled_ref}`} className="hover:underline">
          {t("named", { name })}
        </Link>
      ) : (
        t("outcome.autoreplies")
      )}
      <span aria-hidden>·</span>
      {/* отрицательный отступ держит высоту строки при кнопке под палец */}
      <SummaryToggle result={result} toggle={toggle} className="-my-2.5 md:-my-2" />
    </span>
  );
}

function Status({
  tone,
  icon: Icon,
  text,
}: {
  tone: Tone;
  icon: typeof CircleCheck;
  text: string;
}) {
  return (
    <span className={cn("inline-flex items-center gap-1.5", TONE_TEXT[tone])}>
      <Icon className="size-4 shrink-0" />
      {text}
    </span>
  );
}

export function InboxListSkeleton() {
  return (
    <div className="divide-y rounded-lg border">
      {Array.from({ length: 6 }, (_, i) => (
        <div key={i} className="flex items-center gap-3 px-4 py-3">
          <Skeleton className="h-4 w-12" />
          <Skeleton className="h-4 w-64" />
          <Skeleton className="ml-auto h-4 w-40" />
        </div>
      ))}
    </div>
  );
}

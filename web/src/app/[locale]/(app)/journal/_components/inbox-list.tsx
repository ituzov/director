"use client";

import { ChevronRight, Inbox, Mail, MessageCircle, MousePointerClick } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { useId, useState } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { Link } from "@/i18n/navigation";
import type { Tone } from "@/lib/deliveries";
import { explain, type ResultTab } from "@/lib/events";
import type { InboxItem, InboxPage } from "@/lib/inbox";
import { cn } from "@/lib/utils";

import { loadInbox } from "../actions";
import { longTime, shortTime, type T, who } from "./labels";
import { MoreButton } from "./more-button";
import { useFeed } from "./use-feed";

type Props = {
  accountId: string;
  tab: ResultTab;
  initial: InboxPage;
  // название автоответа по id: handled_ref у событий, которые взяли автоответы
  names: Record<string, string>;
  // момент запроса страницы: «сегодня» в браузере совпадёт с серверным
  now: number;
};

const KIND_ICON = { comment: MessageCircle, postback: MousePointerClick, message: Mail } as const;

// вложения, у которых есть подпись; остальные общим словом
const ATTACHMENTS = ["ig_reel", "image", "video", "audio", "share", "story_mention"] as const;

// колонки: вид, что пришло, чем кончилось, когда, стрелка. На телефоне итог второй строкой
const ROW =
  "grid grid-cols-[1rem_minmax(0,1fr)_auto] gap-x-3 gap-y-1 px-4 md:grid-cols-[1rem_minmax(0,1.4fr)_minmax(0,1fr)_4.5rem_1rem] md:gap-x-4 md:items-center";

const DOT: Record<Tone, string> = {
  ok: "bg-success-foreground",
  warn: "bg-warning-foreground",
  bad: "bg-destructive",
  muted: "bg-muted-foreground/50",
};

function oneOf<V extends string>(list: readonly V[], value: string | null): value is V {
  return value !== null && (list as readonly string[]).includes(value);
}

/** Все события от Meta таблицей: что пришло и чем кончился разбор. Только сам разбор,
 * историю выдач не собираем: она во «Выдачах». */
export function InboxList({ accountId, tab, initial, names, now }: Props) {
  const t = useTranslations("Inbox");
  const { items, next, failed, pending, more } = useFeed(initial, {}, (before) =>
    loadInbox(accountId, before, tab),
  );

  if (items.length === 0) {
    return (
      // как пустые списки у Dokploy: крупная иконка по центру, под ней подсказка
      <div className="grid justify-items-center gap-2 py-10 text-center text-sm">
        <Inbox className="size-8 text-muted-foreground" />
        <p className="font-medium">{t(tab === "all" ? "empty" : "emptyResult")}</p>
        {tab === "all" && (
          <p className="max-w-md text-muted-foreground">
            {t.rich("emptyHint", {
              link: (chunks) => (
                <Link href="/settings/meta" className="text-foreground underline">
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
          <span />
          <span>{t("columns.what")}</span>
          <span>{t("columns.result")}</span>
          <span className="text-right">{t("columns.when")}</span>
          <span />
        </div>
        <ul className="divide-y">
          {items.map((item) => (
            <Row key={item.id} item={item} names={names} now={now} />
          ))}
        </ul>
      </div>
      {next && <MoreButton pending={pending} failed={failed} onClick={more} />}
    </div>
  );
}

function Row({ item, names, now }: { item: InboxItem; names: Props["names"]; now: number }) {
  const t = useTranslations("Inbox");
  const format = useFormatter();
  const [open, setOpen] = useState(false);
  const detailsId = useId();
  const Icon = KIND_ICON[item.kind];
  const at = new Date(item.received_at);
  const name = item.handled_ref ? names[item.handled_ref] : undefined;
  const { result, why } = explain(item, name);
  const resultText = t(result.key, result.params);
  const text = what(item, t);
  // итог со ссылкой на автоответ, если его название известно
  const autoreply = item.handled_by === "autoreplies" && item.handled_ref && name;

  return (
    <li>
      {/* кнопка раскрытия растянута на всю строку (after:inset-0), а ссылка на автоответ
          лежит поверх неё: соседи, а не ссылка внутри кнопки */}
      <div
        className={cn(
          ROW,
          "relative py-3 text-sm hover:bg-muted/50 has-[button:focus-visible]:outline-2 has-[button:focus-visible]:-outline-offset-2 has-[button:focus-visible]:outline-ring",
        )}
      >
        <Icon aria-hidden className="size-4 text-muted-foreground" />
        <button
          type="button"
          aria-expanded={open}
          aria-controls={detailsId}
          onClick={() => setOpen((v) => !v)}
          className="min-w-0 truncate text-left outline-none after:absolute after:inset-0"
          title={text ?? undefined}
        >
          <span className="sr-only">{t(`kind.${item.kind}`)}: </span>
          <span className="font-medium">{who(item, t)}</span>
          {text && <span className="text-muted-foreground"> {text}</span>}
        </button>
        <time
          dateTime={item.received_at}
          title={longTime(at, format)}
          className="col-start-3 row-start-1 text-right font-mono text-xs text-muted-foreground tabular-nums md:col-start-4"
        >
          {shortTime(at, now, format)}
        </time>
        {/* точка в своей колонке: итог начинается с одной линии во всех строках */}
        <span className="col-span-2 col-start-2 grid min-w-0 grid-cols-[0.375rem_minmax(0,1fr)] items-center gap-x-2 md:col-span-1 md:col-start-3 md:row-start-1">
          <span aria-hidden className={cn("size-1.5 rounded-full", DOT[result.tone])} />
          {autoreply ? (
            <Link
              href={`/autoreplies/${item.handled_ref}`}
              className="relative z-10 -my-2.5 inline-flex min-h-10 max-w-full items-center hover:underline md:-my-2 md:min-h-9"
            >
              <span className="truncate">{resultText}</span>
            </Link>
          ) : (
            <span
              className={cn(
                "truncate",
                result.tone === "bad" && "text-destructive",
                result.tone === "muted" && "text-muted-foreground",
              )}
              title={resultText}
            >
              {resultText}
            </span>
          )}
        </span>
        <ChevronRight
          aria-hidden
          className={cn(
            "hidden size-4 text-muted-foreground transition-transform md:col-start-5 md:row-start-1 md:block",
            open && "rotate-90",
          )}
        />
      </div>
      {/* сведения о самом событии: что пришло и как его разобрали */}
      <dl
        id={detailsId}
        hidden={!open}
        className="grid grid-cols-[7rem_minmax(0,1fr)] gap-x-4 gap-y-1.5 px-4 pb-4 text-sm wrap-anywhere md:pl-11"
      >
        <dt className="text-muted-foreground">{t("details.received")}</dt>
        <dd>{longTime(at, format)}</dd>
        <dt className="text-muted-foreground">{t("details.from")}</dt>
        <dd>
          {who(item, t)}
          {item.person_id && <span className="text-muted-foreground"> · id {item.person_id}</span>}
        </dd>
        {text && (
          <>
            <dt className="text-muted-foreground">{t(`kind.${item.kind}`)}</dt>
            <dd>{text}</dd>
          </>
        )}
        {item.media_id && (
          <>
            <dt className="text-muted-foreground">{t("details.post")}</dt>
            <dd className="font-mono text-xs leading-5">{item.media_id}</dd>
          </>
        )}
        <dt className="text-muted-foreground">{t("details.result")}</dt>
        <dd>
          {resultText}. <span className="text-muted-foreground">{t(why.key, why.params)}</span>
        </dd>
      </dl>
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

export function InboxListSkeleton() {
  return (
    <div className="divide-y rounded-lg border">
      {Array.from({ length: 6 }, (_, i) => (
        <div key={i} className="flex items-center gap-3 px-4 py-3">
          <Skeleton className="size-4" />
          <Skeleton className="h-4 w-64" />
          <Skeleton className="ml-auto h-4 w-40" />
        </div>
      ))}
    </div>
  );
}

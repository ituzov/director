"use client";

import { ChevronRight, Inbox } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { useId, useState } from "react";

import { Link } from "@/i18n/navigation";
import { type Delivery, type DeliveryPage, STAGE_TONE, type Tab, waiting } from "@/lib/deliveries";
import { type History, type Step, stages } from "@/lib/inbox";
import { cn } from "@/lib/utils";

import { loadDeliveries } from "../actions";
import { longTime, shortTime, who } from "./labels";
import { MoreButton } from "./more-button";
import { Steps } from "./steps";
import { useFeed } from "./use-feed";

// колонки: человек, автоответ, сейчас, когда, стрелка. На телефоне строка карточкой
const ROW =
  "grid grid-cols-[minmax(0,1fr)_auto] gap-x-4 gap-y-1 px-4 md:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_minmax(0,1fr)_4.5rem_1rem] md:items-center";

const DOT = {
  ok: "bg-success-foreground",
  warn: "bg-warning-foreground",
  bad: "bg-destructive",
  muted: "bg-muted-foreground/50",
} as const;

/** Выдачи на вкладке таблицей: кто, каким автоответом, на каком шаге сейчас. */
export function DeliveryTable({
  accountId,
  tab,
  initial,
  history: initialHistory,
  now,
}: {
  accountId: string;
  tab: Tab;
  initial: DeliveryPage;
  history: History;
  // момент запроса страницы: «сегодня» в браузере совпадёт с серверным
  now: number;
}) {
  const t = useTranslations("Inbox");
  const { items, history, next, failed, pending, more } = useFeed(
    initial,
    initialHistory,
    (before) => loadDeliveries(accountId, before, tab),
  );

  if (items.length === 0) {
    return (
      <div className="grid justify-items-center gap-2 py-10 text-center text-sm">
        <Inbox className="size-8 text-muted-foreground" />
        <p className="font-medium">
          {t(tab === "all" ? "deliveries.empty" : "deliveries.emptyTab")}
        </p>
        {tab === "all" && (
          <p className="max-w-md text-muted-foreground">
            {t.rich("deliveries.emptyHint", {
              link: (chunks) => (
                <Link href="/journal?view=all" className="text-foreground underline">
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
          <span>{t("columns.autoreply")}</span>
          <span>{t("columns.now")}</span>
          <span className="text-right">{t("columns.when")}</span>
          <span />
        </div>
        <ul className="divide-y">
          {items.map((d) => (
            <Row key={d.id} delivery={d} steps={history[d.comment_id] ?? []} now={now} />
          ))}
        </ul>
      </div>
      {next && <MoreButton pending={pending} failed={failed} onClick={more} />}
    </div>
  );
}

function Row({ delivery: d, steps, now }: { delivery: Delivery; steps: Step[]; now: number }) {
  const t = useTranslations("Inbox");
  const format = useFormatter();
  const [open, setOpen] = useState(false);
  const stepsId = useId();
  const at = new Date(d.created_at);
  // путь словами: только пройденные этапы. Текущий уже назван в «Сейчас», а неудачу
  // и непроверенную подписку путь не пересказывает
  const path = stages(steps)
    ?.filter(({ state }) => state === "done")
    .map(({ stage }) => t(`stage.${stage}`))
    .join(" → ");
  const wait = waiting(d, now);
  // под этапом: сколько ждём человека, а у остальных пройденный путь
  const below = wait ? t(`waiting.${wait.unit}`, { count: wait.count }) : path;

  return (
    <li>
      {/* кнопка раскрытия растянута на всю строку (after:inset-0), а ссылка на автоответ
          лежит поверх неё: соседи, а не ссылка внутри кнопки */}
      <div
        className={cn(
          ROW,
          // ждём дольше недели: приглушаем, но не прячем, нажать можно и потом
          wait?.stale && "opacity-60",
          "relative py-3 text-sm hover:bg-muted/50 has-[button:focus-visible]:outline-2 has-[button:focus-visible]:-outline-offset-2 has-[button:focus-visible]:outline-ring",
        )}
      >
        <button
          type="button"
          aria-expanded={open}
          aria-controls={stepsId}
          onClick={() => setOpen((v) => !v)}
          className="min-w-0 text-left outline-none after:absolute after:inset-0"
        >
          <span className="block truncate font-medium">{who(d, t)}</span>
          {d.text && (
            <span className="block truncate text-muted-foreground" title={d.text}>
              «{d.text}»
            </span>
          )}
        </button>
        <time
          dateTime={d.created_at}
          title={longTime(at, format)}
          className="col-start-2 row-start-1 self-start text-right font-mono text-xs text-muted-foreground tabular-nums md:col-start-4 md:self-center"
        >
          {shortTime(at, now, format)}
        </time>
        <span className="col-span-2 flex min-w-0 items-center text-muted-foreground md:col-span-1 md:col-start-2 md:row-start-1">
          <span className="shrink-0 md:hidden">{t("columns.autoreply")}:&nbsp;</span>
          <Link
            href={`/autoreplies/${d.autoreply_id}`}
            className={
              "relative z-10 -my-2.5 inline-flex min-h-10 max-w-full items-center hover:text-foreground hover:underline md:-my-2 md:min-h-9"
            }
          >
            <span className="truncate">{d.autoreply_name}</span>
          </Link>
        </span>
        {/* точка в своей колонке: этап и путь под ним начинаются с одной линии; узкая
            колонка на md обрезается, а не наезжает на «Когда» */}
        <span className="col-span-2 grid min-w-0 grid-cols-[0.375rem_minmax(0,1fr)] items-center gap-x-2 md:col-span-1 md:col-start-3 md:row-start-1">
          <span aria-hidden className={cn("size-1.5 rounded-full", DOT[STAGE_TONE[d.stage]])} />
          <span
            className={cn("truncate", STAGE_TONE[d.stage] === "bad" && "text-destructive")}
            title={t(`stageNow.${d.stage}`)}
          >
            {t(`stageNow.${d.stage}`)}
          </span>
          {below && (
            <span className="col-start-2 truncate text-xs text-muted-foreground">{below}</span>
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
      <div id={stepsId} hidden={!open} className="grid gap-3 px-4 pb-4">
        {steps.length > 0 ? (
          <Steps
            id={`${stepsId}-steps`}
            open
            steps={steps}
            className="grid-cols-[3.5rem_minmax(0,1fr)] gap-x-3 text-sm"
          />
        ) : (
          <p className="text-sm text-muted-foreground">{t("deliveries.noHistory")}</p>
        )}
      </div>
    </li>
  );
}

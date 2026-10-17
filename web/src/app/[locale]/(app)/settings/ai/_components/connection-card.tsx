"use client";

import { useFormatter, useTranslations } from "next-intl";
import { useState } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { useInBrowser } from "@/hooks/use-in-browser";
import { type AiConnection, type AiTask, isKnownProvider, stampOf } from "@/lib/ai";
import { cn } from "@/lib/utils";

import type { Checked } from "../actions";
import { ConnectionActions } from "./connection-actions";

// сколько задач видно сразу, остальные под «Ещё N»
const TASKS_SHOWN = 3;

export function ConnectionCard({ connection }: { connection: AiConnection }) {
  const t = useTranslations("Ai");
  // итог последней проверки с этой карточки
  const [checked, setChecked] = useState<(Checked & { replaced: boolean }) | null>(null);
  const known = isKnownProvider(connection.provider);
  // вид, который записала версия api новее: как есть
  const provider = isKnownProvider(connection.provider)
    ? t(`providers.${connection.provider}`)
    : connection.provider;
  // показываем, пока карточка в том состоянии, про которое итог: иначе он устарел
  const fresh = checked && checked.stamp === stampOf(connection) ? checked : null;

  return (
    <article
      className={cn(
        "flex h-full flex-col gap-4 rounded-xl border bg-card p-4",
        // поломку видно с первого взгляда на список: полоса слева
        connection.error_code && "border-l-2 border-l-destructive",
      )}
    >
      <header className="grid gap-1">
        <h3 className="truncate font-medium">{connection.name}</h3>
        <p className="truncate text-sm text-muted-foreground">
          {provider} · <span className="font-mono">…{connection.key_hint}</span>
        </p>
      </header>
      <Status connection={connection} />
      {fresh && (
        <p
          role="status"
          className={cn("text-sm", fresh.check === "ok" ? "text-brand" : "text-muted-foreground")}
        >
          {fresh.replaced && `${t("check.replaced")} `}
          {t(`check.${fresh.check}`)}
        </p>
      )}
      {!known && <p className="text-sm text-muted-foreground">{t("unknownProvider")}</p>}
      <Tasks tasks={connection.tasks} />
      <footer className="mt-auto border-t pt-4">
        <ConnectionActions connection={connection} canChange={known} onChecked={setChecked} />
      </footer>
    </article>
  );
}

function Status({ connection }: { connection: AiConnection }) {
  const t = useTranslations("Ai.status");
  const format = useFormatter();
  const inBrowser = useInBrowser();
  const date = (iso: string) => format.dateTime(new Date(iso), { dateStyle: "medium" });

  // дата в поясе браузера: до гидрации держим место
  if (!inBrowser) return <Skeleton className="h-5 w-32" />;
  if (connection.error_code && connection.error_at) {
    return (
      <div role="alert" className="grid gap-1 text-sm">
        <span className="font-medium text-destructive">
          {t(`errors.${connection.error_code}.title`)}
        </span>
        <span className="text-muted-foreground">
          {t("since", { date: date(connection.error_at) })}.{" "}
          {t(`errors.${connection.error_code}.body`)}
        </span>
      </div>
    );
  }
  return (
    <span className="text-sm text-muted-foreground">
      {connection.checked_at ? t("checked", { date: date(connection.checked_at) }) : t("unchecked")}
    </span>
  );
}

function Tasks({ tasks }: { tasks: AiTask[] }) {
  const t = useTranslations("Ai.tasks");
  const [all, setAll] = useState(false);

  if (tasks.length === 0) {
    return <p className="text-sm text-muted-foreground">{t("empty")}</p>;
  }
  const shown = all ? tasks : tasks.slice(0, TASKS_SHOWN);
  return (
    <div className="grid gap-2">
      <h4 className="text-xs text-muted-foreground">{t("title")}</h4>
      <ul className="grid divide-y text-sm">
        {shown.map((task) => (
          <li key={task.purpose} className="flex justify-between gap-3 py-2 first:pt-0">
            {/* имена задач для людей появятся вместе с первой задачей (ассистент) */}
            <span className="min-w-0 truncate">{task.purpose}</span>
            <span
              className={cn(
                "shrink-0 font-mono text-xs",
                task.model_missing ? "text-destructive" : "text-muted-foreground",
              )}
            >
              {task.model_missing
                ? t("modelMissing")
                : task.models.length === 1
                  ? task.models[0]
                  : t("models", { count: task.models.length })}
            </span>
          </li>
        ))}
      </ul>
      {!all && tasks.length > TASKS_SHOWN && (
        <button
          type="button"
          onClick={() => setAll(true)}
          className="justify-self-start text-sm text-muted-foreground hover:text-foreground"
        >
          {t("more", { count: tasks.length - TASKS_SHOWN })}
        </button>
      )}
    </div>
  );
}

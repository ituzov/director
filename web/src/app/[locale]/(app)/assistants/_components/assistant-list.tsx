"use client";

import { Archive, ArchiveRestore, Ellipsis, Pencil } from "lucide-react";
import { useTranslations } from "next-intl";
import { useOptimistic, useState, useTransition } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Link } from "@/i18n/navigation";
import type { Assistant, AssistantConflict } from "@/lib/assistants";
import { cn } from "@/lib/utils";

import { archive, setEnabled, unarchive } from "../actions";

type Props = {
  assistants: Assistant[];
  archived: boolean;
  // менять может владелец: остальным без переключателя и меню
  canEdit: boolean;
};

export function AssistantList({ assistants, archived, canEdit }: Props) {
  const t = useTranslations("Assistants");

  if (assistants.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">{t(archived ? "emptyArchive" : "empty")}</p>
    );
  }
  // частные с постами рядом с общим: «все посты, кроме N» считаем по ним
  const privatePosts = assistants
    .filter((a) => a.scope === "posts")
    .reduce((n, a) => n + a.media_ids.length, 0);
  return (
    // как у автоответов: сколько карточек по 22rem влезает в ряд, столько и ставим
    <ul className="grid grid-cols-[repeat(auto-fill,minmax(min(100%,22rem),1fr))] gap-4">
      {assistants.map((assistant) => (
        <AssistantCard
          key={assistant.id}
          assistant={assistant}
          archived={archived}
          canEdit={canEdit}
          privatePosts={privatePosts}
        />
      ))}
    </ul>
  );
}

function AssistantCard({
  assistant,
  archived,
  canEdit,
  privatePosts,
}: {
  assistant: Assistant;
  archived: boolean;
  canEdit: boolean;
  privatePosts: number;
}) {
  const t = useTranslations("Assistants");
  const [pending, startTransition] = useTransition();
  // переключатель щёлкает сразу, не дожидаясь api
  const [enabled, setOptimistic] = useOptimistic(assistant.enabled);
  const [conflict, setConflict] = useState<AssistantConflict | null>(null);
  // на паузе в архиве и так не работает: приглушаем только активные
  const off = !archived && !enabled;

  function toggle(next: boolean) {
    startTransition(async () => {
      setOptimistic(next);
      await setEnabled(assistant.id, next);
    });
  }

  function restore() {
    startTransition(async () => {
      const result = await unarchive(assistant.id);
      setConflict(result.conflict ?? null);
    });
  }

  const where =
    assistant.scope === "all"
      ? privatePosts > 0
        ? t("allPostsExcept", { count: privatePosts })
        : t("allPosts")
      : t("posts", { count: assistant.media_ids.length });

  return (
    // вся карточка ведёт в правку: ссылка на названии растянута на неё (after:inset-0),
    // а переключатель и меню подняты над ней
    <li
      className="relative flex min-h-44 flex-col gap-4 rounded-xl border p-5 transition-colors hover:bg-muted/40"
      aria-busy={pending}
    >
      <div className="flex items-center justify-between gap-3">
        <Link
          href={`/assistants/${assistant.id}`}
          className={cn(
            "min-w-0 truncate font-medium after:absolute after:inset-0 after:rounded-xl",
            off && "text-muted-foreground",
          )}
        >
          {assistant.name}
        </Link>
        {canEdit && (
          <div className="relative z-10 flex shrink-0 items-center gap-2">
            {!archived && (
              <Switch
                checked={enabled}
                onCheckedChange={toggle}
                aria-label={t("enabled", { name: assistant.name })}
              />
            )}
            <DropdownMenu>
              <DropdownMenuTrigger
                render={<Button variant="ghost" size="icon" aria-label={t("menu")} />}
              >
                <Ellipsis />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem render={<Link href={`/assistants/${assistant.id}`} />}>
                  <Pencil />
                  {t("edit")}
                </DropdownMenuItem>
                {archived ? (
                  <DropdownMenuItem onClick={restore}>
                    <ArchiveRestore />
                    {t("unarchive")}
                  </DropdownMenuItem>
                ) : (
                  <DropdownMenuItem onClick={() => startTransition(() => archive(assistant.id))}>
                    <Archive />
                    {t("archive")}
                  </DropdownMenuItem>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        )}
      </div>

      <div className={cn("flex flex-wrap gap-1.5", off && "opacity-60")}>
        <Badge variant="outline">{where}</Badge>
        <Badge variant="outline">{t(`modes.${assistant.mode}`)}</Badge>
        {assistant.model && (
          <Badge
            variant="outline"
            className={cn("font-mono", assistant.model_missing && "text-destructive")}
          >
            {assistant.model}
          </Badge>
        )}
        {!assistant.connection_id && (
          <Badge variant="outline" className="text-destructive">
            {t("noConnection")}
          </Badge>
        )}
      </div>
      {off && <p className="text-xs text-muted-foreground">{t(`paused.${assistant.scope}`)}</p>}
      {/* подвал прижат к низу: у всех карточек ряда цифры на одной линии */}
      <p
        className={cn(
          "mt-auto border-t pt-3 text-xs text-muted-foreground tabular-nums",
          off && "opacity-60",
        )}
      >
        {t("today", { answered: assistant.today.answered, unsure: assistant.today.unsure })}
      </p>
      {conflict && (
        <p className="relative z-10 text-sm text-destructive" role="alert">
          {t(`conflict.${conflict.kind}`, { name: conflict.assistant.name })}
        </p>
      )}
    </li>
  );
}

export function AssistantListSkeleton() {
  return (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(min(100%,20rem),1fr))] gap-3">
      {[0, 1].map((n) => (
        <div key={n} className="grid gap-2 rounded-xl border p-4">
          <Skeleton className="h-5 w-40" />
          <Skeleton className="h-5 w-56" />
        </div>
      ))}
    </div>
  );
}

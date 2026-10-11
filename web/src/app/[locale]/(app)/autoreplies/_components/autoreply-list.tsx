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
import type { Autoreply, AutoreplyConflict } from "@/lib/autoreplies";

import { archive, setEnabled, unarchive } from "../actions";

type Props = { autoreplies: Autoreply[]; archived: boolean };

export function AutoreplyList({ autoreplies, archived }: Props) {
  const t = useTranslations("Autoreplies");

  if (autoreplies.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">{t(archived ? "emptyArchive" : "empty")}</p>
    );
  }
  return (
    // сколько карточек по 20rem влезает в ряд, столько и ставим, как проекты у Dokploy.
    // min(100%, …): на узком телефоне карточка не вылезает за край
    <ul className="grid grid-cols-[repeat(auto-fill,minmax(min(100%,20rem),1fr))] gap-3">
      {autoreplies.map((autoreply) => (
        <AutoreplyCard key={autoreply.id} autoreply={autoreply} archived={archived} />
      ))}
    </ul>
  );
}

function AutoreplyCard({ autoreply, archived }: { autoreply: Autoreply; archived: boolean }) {
  const t = useTranslations("Autoreplies");
  const [pending, startTransition] = useTransition();
  // переключатель щёлкает сразу, не дожидаясь api
  const [enabled, setOptimistic] = useOptimistic(autoreply.enabled);
  const [conflict, setConflict] = useState<AutoreplyConflict | null>(null);

  function toggle(next: boolean) {
    startTransition(async () => {
      setOptimistic(next);
      await setEnabled(autoreply.id, next);
    });
  }

  function restore() {
    startTransition(async () => {
      const result = await unarchive(autoreply.id);
      setConflict(result.conflict ?? null);
    });
  }

  return (
    // вся карточка ведёт в правку: ссылка на названии растянута на неё (after:inset-0),
    // а переключатель и меню подняты над ней
    <li
      className="relative flex flex-col gap-3 rounded-xl border p-4 transition-colors hover:bg-muted/40"
      aria-busy={pending}
    >
      <div className="flex items-start justify-between gap-3">
        {/* flex-1: колонка занимает всё место до переключателя, иначе бейджи
            переносились по одному, хотя ряд свободен */}
        <div className="grid min-w-0 flex-1 gap-2">
          <Link
            href={`/autoreplies/${autoreply.id}`}
            className="truncate font-medium after:absolute after:inset-0 after:rounded-xl"
          >
            {autoreply.name}
          </Link>
          <div className="flex flex-wrap gap-1.5">
            {autoreply.keywords.map((word) => (
              <Badge key={word} variant="secondary">
                {word}
              </Badge>
            ))}
          </div>
          <div className="flex flex-wrap gap-1.5">
            <Badge variant="outline">
              {autoreply.scope === "all"
                ? t("allPosts")
                : t("posts", { count: autoreply.media_ids.length })}
            </Badge>
            {autoreply.follow_gate && <Badge variant="outline">{t("followGate")}</Badge>}
          </div>
        </div>
        <div className="relative z-10 flex shrink-0 items-center gap-2">
          {!archived && (
            <Switch
              checked={enabled}
              onCheckedChange={toggle}
              aria-label={t("enabled", { name: autoreply.name })}
            />
          )}
          <DropdownMenu>
            <DropdownMenuTrigger
              render={<Button variant="ghost" size="icon" aria-label={t("menu")} />}
            >
              <Ellipsis />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem render={<Link href={`/autoreplies/${autoreply.id}`} />}>
                <Pencil />
                {t("edit")}
              </DropdownMenuItem>
              {archived ? (
                <DropdownMenuItem onClick={restore}>
                  <ArchiveRestore />
                  {t("unarchive")}
                </DropdownMenuItem>
              ) : (
                <DropdownMenuItem onClick={() => startTransition(() => archive(autoreply.id))}>
                  <Archive />
                  {t("archive")}
                </DropdownMenuItem>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
      {conflict && (
        <p className="relative z-10 text-sm text-destructive" role="alert">
          {t(`conflict.${conflict.kind}`, { value: conflict.value, name: conflict.autoreply.name })}
        </p>
      )}
    </li>
  );
}

export function AutoreplyListSkeleton() {
  return (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(min(100%,20rem),1fr))] gap-3">
      {[0, 1, 2].map((n) => (
        <div key={n} className="grid gap-2 rounded-xl border p-4">
          <Skeleton className="h-5 w-40" />
          <Skeleton className="h-5 w-56" />
        </div>
      ))}
    </div>
  );
}

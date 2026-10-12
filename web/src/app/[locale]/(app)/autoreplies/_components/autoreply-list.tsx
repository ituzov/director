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
import { cn } from "@/lib/utils";

import { archive, setEnabled, unarchive } from "../actions";

type Props = { autoreplies: Autoreply[]; archived: boolean };

const MAX_WORDS = 6;

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
  // выключенный в архиве и так не работает: приглушаем только активные
  const off = !archived && !enabled;
  // слов бывает до 50: в карточке первые, остальное числом
  const words = autoreply.keywords.slice(0, MAX_WORDS);
  const hidden = autoreply.keywords.length - words.length;

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
      <div className="flex items-center justify-between gap-3">
        <Link
          href={`/autoreplies/${autoreply.id}`}
          className={cn(
            "min-w-0 truncate font-medium after:absolute after:inset-0 after:rounded-xl",
            off && "text-muted-foreground",
          )}
        >
          {autoreply.name}
        </Link>
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

      {/* под шапкой на всю ширину карточки: рядом с переключателем бейджам было тесно */}
      <div className={cn("grid gap-2", off && "opacity-60")}>
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-xs text-muted-foreground">{t("keywords")}</span>
          {words.map((word) => (
            <Badge key={word} variant="secondary">
              {t("word", { word })}
            </Badge>
          ))}
          {hidden > 0 && <Badge variant="secondary">{t("moreWords", { count: hidden })}</Badge>}
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

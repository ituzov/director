"use client";

import { CircleCheck, Download, ExternalLink, Server } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useCallback, useState, useTransition } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { SidebarMenu, SidebarMenuButton, SidebarMenuItem } from "@/components/ui/sidebar";
import type { LocalizedText, Release, Updates } from "@/lib/updates";

import { requestUpdate, type UpdateRequestError } from "../actions";
import { ReleaseNotes } from "./release-notes";
import { UpdateProgress } from "./update-progress";

// страница релиза на GitHub строится из номера: в versions.json ссылку не храним
const RELEASES_URL = "https://github.com/ituzov/director/releases/tag/v";

// info: версии и заметки; confirm: что будет; progress: ход обновления
type Stage = "info" | "confirm" | "progress";

/**
 * Окно обновления. Открывают его два входа в меню: заметная кнопка над
 * профилем (только когда есть новая версия) и тихая строка версии внизу.
 * Данные пришли с меню с сервера: окно открывается без запроса.
 */
export function UpdateDialog({
  updates,
  trigger,
}: {
  updates: Updates;
  trigger: "button" | "line";
}) {
  const t = useTranslations("App.updates");
  const offer = updates.available;
  const latest = offer?.latest ?? null;
  const canUpdate = latest !== null && offer?.blocked === null;

  const [open, setOpen] = useState(false);
  const [stage, setStage] = useState<Stage>("info");
  const [requestedAt, setRequestedAt] = useState<string | null>(null);
  const [error, setError] = useState<UpdateRequestError | null>(null);
  // пока идёт обновление, окно не закрыть: иначе человек не узнает, чем кончилось
  const [locked, setLocked] = useState(false);
  const [pending, startTransition] = useTransition();
  const unlock = useCallback(() => setLocked(false), []);

  const changeOpen = (next: boolean) => {
    if (locked) return;
    setOpen(next);
    if (!next) {
      setStage("info");
      setError(null);
    }
  };

  const start = () =>
    startTransition(async () => {
      if (!latest) return;
      const result = await requestUpdate(latest);
      if ("error" in result) {
        setError(result.error);
        return;
      }
      setRequestedAt(result.at);
      setLocked(true);
      setStage("progress");
    });

  return (
    <Dialog open={open} onOpenChange={changeOpen}>
      {trigger === "button" ? (
        <SidebarMenu>
          <SidebarMenuItem>
            <DialogTrigger
              render={
                <SidebarMenuButton
                  variant="outline"
                  tooltip={t("available", { version: latest ?? "" })}
                  className="h-9 justify-center font-medium"
                />
              }
            >
              <Download />
              {/* Точка видна и в свёрнутом меню: там остаётся только иконка. Стоит
                  до подписи нарочно: последнему span кнопка меню ставит truncate,
                  а с ним overflow: hidden, и пульс обрезался в квадрат */}
              <span aria-hidden className="absolute top-1.5 right-1.5 flex size-2">
                <span className="absolute inline-flex size-full animate-ping rounded-full bg-brand/60 motion-reduce:hidden" />
                <span className="relative inline-flex size-2 rounded-full bg-brand" />
              </span>
              <span>{t("availableShort")}</span>
            </DialogTrigger>
          </SidebarMenuItem>
        </SidebarMenu>
      ) : (
        <DialogTrigger
          render={
            <button
              type="button"
              className="w-full rounded-md py-1 text-center text-xs text-muted-foreground transition-colors group-data-[collapsible=icon]:hidden hover:text-foreground"
            />
          }
        >
          {t("version", { version: updates.current })}
        </DialogTrigger>
      )}

      <DialogContent className="sm:max-w-lg" showCloseButton={!locked} closeLabel={t("close")}>
        <DialogHeader className="flex-row flex-wrap items-center gap-x-3 gap-y-1 pr-8">
          <DialogTitle className="text-lg">
            {stage === "info" ? t("title") : t("to", { version: latest ?? "" })}
          </DialogTitle>
          <Badge variant="secondary" className="gap-1">
            <Server />v{updates.current}
          </Badge>
          {/* для диктора: заголовок и версия выше видны глазами */}
          <DialogDescription className="sr-only">
            {t("current", { version: updates.current })}
          </DialogDescription>
        </DialogHeader>

        {stage === "progress" && latest && (
          <UpdateProgress target={latest} requestedAt={requestedAt} onFinish={unlock} />
        )}

        {stage === "confirm" && (
          <>
            <ul className="grid list-disc gap-1 pl-5">
              <li>{t("confirm.backup")}</li>
              <li>{t("confirm.downtime")}</li>
              <li>{t("confirm.rollback")}</li>
            </ul>
            {error && <p className="text-destructive">{t(`errors.${error}`)}</p>}
            <DialogFooter>
              <Button variant="outline" onClick={() => setStage("info")} disabled={pending}>
                {t("confirm.back")}
              </Button>
              <Button onClick={start} disabled={pending}>
                <Download />
                {t("confirm.start")}
              </Button>
            </DialogFooter>
          </>
        )}

        {stage === "info" && (
          <>
            {/* заметки бывают длинными: середина окна прокручивается */}
            <div className="-mx-4 grid max-h-[60dvh] gap-4 overflow-y-auto px-4">
              {updates.error ? (
                <p>{t("error")}</p>
              ) : latest ? (
                <Callout icon={<Download />}>{t("latest", { version: latest })}</Callout>
              ) : (
                <Callout icon={<CircleCheck />}>{t("upToDate")}</Callout>
              )}
              {updates.message && <Notice tone="muted" text={updates.message} />}
              {offer?.releases.map((release, i) => (
                <ReleaseBlock key={release.version} release={release} open={i === 0} />
              ))}
            </div>

            <DialogFooter>
              {/* обновиться нельзя: причина вместо кнопки, а не молча серая кнопка */}
              {latest && offer?.blocked && (
                <p className="mr-auto self-center text-muted-foreground">
                  {offer.blocked === "min_from"
                    ? t("blocked.min_from", { version: offer.min_from ?? "" })
                    : t(`blocked.${offer.blocked}`)}
                </p>
              )}
              <DialogClose render={<Button variant="outline" />}>{t("close")}</DialogClose>
              {canUpdate && (
                <Button onClick={() => setStage("confirm")}>
                  <Download />
                  {t("update", { version: latest })}
                </Button>
              )}
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

/** Последняя версия раскрыта, предыдущие свёрнуты: главное видно сразу. */
function ReleaseBlock({ release, open }: { release: Release; open: boolean }) {
  const t = useTranslations("App.updates");
  const text = useLocalized();
  const head = (
    <span className="flex flex-wrap items-center gap-2">
      <span className="font-medium text-foreground">
        {open ? t("whatsNew", { version: release.version }) : release.version}
      </span>
      <span className="text-xs text-muted-foreground">{release.date}</span>
      {release.breaking && <Badge variant="destructive">{t("breaking")}</Badge>}
      {release.security && <Badge variant="secondary">{t("security")}</Badge>}
      <a
        href={`${RELEASES_URL}${release.version}`}
        target="_blank"
        rel="noreferrer"
        className="ml-auto inline-flex items-center gap-1 text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
      >
        {t("onGithub")}
        <ExternalLink className="size-3" />
      </a>
    </span>
  );
  const body = (
    <>
      {release.important && <Notice tone="warning" text={release.important} />}
      <ReleaseNotes text={text(release.notes)} />
    </>
  );

  if (open) {
    return (
      <section className="grid gap-3">
        {head}
        {body}
      </section>
    );
  }
  return (
    <details className="group grid gap-3 border-t pt-3">
      <summary className="cursor-pointer list-none">{head}</summary>
      <div className="mt-3 grid gap-3">{body}</div>
    </details>
  );
}

function Callout({ icon, children }: { icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <p className="flex items-center gap-2 rounded-lg border border-brand/20 bg-brand/10 px-3 py-2 font-medium text-brand [&_svg]:size-4 [&_svg]:shrink-0">
      {icon}
      {children}
    </p>
  );
}

function Notice({ tone, text }: { tone: "warning" | "muted"; text: LocalizedText }) {
  const localized = useLocalized();
  return (
    <p
      className={
        tone === "warning"
          ? "rounded-lg bg-warning px-3 py-2 whitespace-pre-line text-warning-foreground"
          : "rounded-lg bg-muted px-3 py-2 whitespace-pre-line"
      }
    >
      {localized(text)}
    </p>
  );
}

/** Текст с сайта на языке админки. Языков у сайта два: всё не русское на английском. */
function useLocalized() {
  const locale = useLocale();
  return (text: LocalizedText) => (locale === "ru" ? text.ru : text.en);
}

"use client";

import { Check, Clapperboard, X } from "lucide-react";
import { useFormatter, useNow, useTranslations } from "next-intl";
import { useEffect, useState } from "react";

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
import { Skeleton } from "@/components/ui/skeleton";
import type { Media } from "@/lib/accounts";
import { cn } from "@/lib/utils";

import { loadMedia, loadSelectedMedia, type MediaPage, type TakenBy } from "../actions";

type Failure = Extract<MediaPage, { failed: unknown }>["failed"];

type Props = {
  // аккаунт автоответа; null при создании: тогда выбранный в меню
  accountId: string | null;
  // сам автоответ при правке: его посты не считаются занятыми
  autoreplyId: string | null;
  // уже выбранные посты при правке
  initial: string[];
};

/** Поле «на каких постах»: ряд выбранных в форме и окно с лентой аккаунта.
 * Форма показывает поле, только когда выбраны посты, и в этот же момент обе загрузки
 * уходят сразу: к нажатию «Выбрать посты» лента обычно уже здесь. */
export function PostPicker({ accountId, autoreplyId, initial }: Props) {
  const t = useTranslations("AutoreplyForm.posts");

  // что уйдёт в форму, и миниатюры к этим id: из ленты или из ручки выбранных
  const [chosen, setChosen] = useState<string[]>(initial);
  const [known, setKnown] = useState<Record<string, Media>>({});
  const [missing, setMissing] = useState<string[]>([]);
  // миниатюры выбранных при правке ещё едут
  const [selectedLoading, setSelectedLoading] = useState(initial.length > 0);

  // лента для окна: живёт здесь, а не в окне, чтобы пережить его закрытие
  const [items, setItems] = useState<Media[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [taken, setTaken] = useState<Record<string, TakenBy>>({});
  const [loading, setLoading] = useState(true);
  const [failure, setFailure] = useState<Failure | null>(null);

  // окно правит копию: «Отмена» её выбрасывает, «Готово» переносит в форму
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<string[]>([]);

  function remember(media: Media[]) {
    setKnown((prev) => ({ ...prev, ...Object.fromEntries(media.map((m) => [m.id, m])) }));
  }

  // страница пришла: первая заменяет ленту, следующие дописываются в конец
  function apply(page: MediaPage, after: string | null) {
    setLoading(false);
    if ("failed" in page) return setFailure(page.failed);
    setFailure(null);
    setItems((prev) => (after ? [...prev, ...page.items] : page.items));
    setNext(page.next);
    // каждая страница приносит свежий список занятых целиком
    setTaken(page.taken);
    remember(page.items);
  }

  useEffect(() => {
    let current = true;
    void fetchPage(accountId, autoreplyId, null).then((page) => current && apply(page, null));
    // миниатюры выбранных при правке: аккаунт тогда известен
    if (accountId && initial.length) {
      void loadSelectedMedia(accountId, initial)
        .catch(() => null)
        .then((result) => {
          if (!current) return;
          setSelectedLoading(false);
          // не вышло: в ряду останутся серые плитки, выбор всё равно сохранится
          if (!result || "failed" in result) return;
          remember(result.items);
          setMissing(result.missing);
        });
    }
    // поле убрали раньше ответа: опоздавший ответ не нужен
    return () => {
      current = false;
    };
    // initial берём один раз при появлении поля, дальше выбор живёт в chosen
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accountId, autoreplyId]);

  function load(after: string | null) {
    setLoading(true);
    void fetchPage(accountId, autoreplyId, after).then((page) => apply(page, after));
  }

  function openDialog(value: boolean) {
    if (value) setDraft(chosen);
    setOpen(value);
  }

  function toggle(id: string, checked: boolean) {
    setDraft((prev) => (checked ? [...prev, id] : prev.filter((x) => x !== id)));
  }

  return (
    <div className="flex flex-col gap-3">
      {chosen.map((id) => (
        <input key={id} type="hidden" name="media_ids" value={id} />
      ))}

      {chosen.length > 0 && (
        <ul className="flex flex-wrap gap-2">
          {chosen.map((id) => (
            <li key={id}>
              <ChosenThumb
                media={known[id] ?? null}
                missing={missing.includes(id)}
                loading={selectedLoading}
                onRemove={() => setChosen((prev) => prev.filter((x) => x !== id))}
              />
            </li>
          ))}
        </ul>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <Dialog open={open} onOpenChange={openDialog}>
          {/* через Trigger: после закрытия фокус вернётся на кнопку */}
          <DialogTrigger render={<Button type="button" variant="outline" />}>
            {chosen.length ? t("change") : t("choose")}
          </DialogTrigger>
          <DialogContent
            closeLabel={t("close")}
            className="flex max-h-[90dvh] flex-col sm:max-w-2xl"
          >
            <DialogHeader>
              <DialogTitle>{t("title")}</DialogTitle>
              <DialogDescription>{t("chosen", { count: draft.length })}</DialogDescription>
            </DialogHeader>

            {/* шапка и кнопки на месте, листается только лента */}
            <div className="-mx-4 flex min-h-0 flex-col gap-3 overflow-y-auto px-4 py-1">
              {items.length > 0 && (
                <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
                  {items.map((media) => (
                    <PostTile
                      key={media.id}
                      media={media}
                      checked={draft.includes(media.id)}
                      takenBy={taken[media.id] ?? null}
                      onChange={(checked) => toggle(media.id, checked)}
                    />
                  ))}
                </div>
              )}

              {loading && items.length === 0 && (
                <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
                  {Array.from({ length: 8 }, (_, i) => (
                    <Skeleton key={i} className="aspect-square rounded-lg" />
                  ))}
                </div>
              )}

              {failure && (
                <div
                  role="alert"
                  className="flex flex-wrap items-center gap-3 text-sm text-destructive"
                >
                  {t(`failed.${failure}`)}
                  {/* токен истёк: повтор не поможет, нужно подключить аккаунт заново */}
                  {failure === "MetaUnavailable" && (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={loading}
                      onClick={() => load(items.length ? next : null)}
                    >
                      {t("retry")}
                    </Button>
                  )}
                </div>
              )}

              {!loading && !failure && items.length === 0 && (
                <p className="text-sm text-muted-foreground">{t("empty")}</p>
              )}

              {next && !failure && (
                <Button
                  type="button"
                  variant="outline"
                  className="self-start"
                  disabled={loading}
                  onClick={() => load(next)}
                >
                  {loading ? t("loading") : t("more")}
                </Button>
              )}
            </div>

            <DialogFooter>
              <DialogClose render={<Button type="button" variant="outline" />}>
                {t("cancel")}
              </DialogClose>
              <Button
                type="button"
                onClick={() => {
                  setChosen(draft);
                  setOpen(false);
                }}
              >
                {t("done")}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
        <p className="text-sm text-muted-foreground">{t("chosen", { count: chosen.length })}</p>
      </div>
    </div>
  );
}

/** Server action может и бросить (сеть, упавший Next): для человека это тот же «не ответили». */
function fetchPage(
  accountId: string | null,
  autoreplyId: string | null,
  after: string | null,
): Promise<MediaPage> {
  return loadMedia(accountId, autoreplyId, after).catch(
    () => ({ failed: "MetaUnavailable" }) as const,
  );
}

/** Выбранный пост в ряду формы: миниатюра и крестик «убрать». */
function ChosenThumb({
  media,
  missing,
  loading,
  onRemove,
}: {
  media: Media | null;
  missing: boolean;
  loading: boolean;
  onRemove: () => void;
}) {
  const t = useTranslations("AutoreplyForm.posts");

  return (
    <div className="relative size-16">
      {media?.thumbnail ? (
        <Thumbnail
          src={media.thumbnail}
          alt={media.caption ?? t("untitled")}
          className="size-16 rounded-lg border"
        />
      ) : loading && !missing ? (
        <Skeleton className="size-16 rounded-lg" />
      ) : (
        // пост удалили, или Meta не ответила: выбор всё равно на месте
        <div className="grid size-16 place-items-center rounded-lg border bg-muted p-1 text-center text-xs text-muted-foreground">
          {missing && t("deleted")}
        </div>
      )}
      <button
        type="button"
        onClick={onRemove}
        aria-label={t("remove")}
        className="absolute -top-1.5 -right-1.5 grid size-5 place-items-center rounded-full border bg-background text-muted-foreground shadow-sm hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
      >
        <X className="size-3" />
      </button>
    </div>
  );
}

function PostTile({
  media,
  checked,
  takenBy,
  onChange,
}: {
  media: Media;
  checked: boolean;
  takenBy: TakenBy | null;
  onChange: (checked: boolean) => void;
}) {
  const t = useTranslations("AutoreplyForm.posts");
  const format = useFormatter();
  const now = useNow();
  const date = media.timestamp ? new Date(media.timestamp) : null;
  // год только у прошлогодних: в плитке тесно. Год в поясе форматтера, а не среды:
  // иначе под Новый год сервер и браузер нарисовали бы разное
  const year = (d: Date) => format.dateTime(d, { year: "numeric" });
  const when =
    date &&
    format.dateTime(date, {
      day: "numeric",
      month: "short",
      ...(year(date) !== year(now) && { year: "numeric" }),
    });

  return (
    <label className="group relative cursor-pointer overflow-hidden rounded-lg border bg-card transition-shadow has-checked:border-primary has-checked:ring-2 has-checked:ring-primary has-focus-visible:ring-3 has-focus-visible:ring-ring/50 has-disabled:cursor-not-allowed">
      <input
        type="checkbox"
        checked={checked}
        // занятый пост не выбрать; уже выбранный можно снять, иначе с него не уйти
        disabled={Boolean(takenBy) && !checked}
        onChange={(e) => onChange(e.target.checked)}
        className="sr-only"
      />
      <div className="relative">
        {/* приглушаем обёртку: у самой картинки своя прозрачность, пока она проявляется */}
        <div className="group-has-disabled:opacity-40">
          {media.thumbnail ? (
            <Thumbnail src={media.thumbnail} alt="" lazy className="aspect-square w-full" />
          ) : (
            <div className="aspect-square w-full bg-muted" />
          )}
        </div>
        {media.type === "REELS" && (
          <span className="absolute top-1.5 left-1.5 rounded-full bg-black/50 p-1 text-white">
            <Clapperboard className="size-3" aria-label={t("reels")} />
          </span>
        )}
        {/* приглушена картинка, а не плашка: плашку надо прочесть */}
        {takenBy && (
          <span className="absolute inset-x-1.5 bottom-1.5 truncate rounded-md bg-background/90 px-1.5 py-0.5 text-xs">
            {t(takenBy.enabled ? "takenBy" : "takenByDisabled", { name: takenBy.name })}
          </span>
        )}
      </div>
      <span className="absolute top-1.5 right-1.5 grid size-5 place-items-center rounded-full border-2 border-white bg-black/20 group-has-checked:border-primary group-has-checked:bg-primary group-has-disabled:hidden">
        <Check className="size-3 text-primary-foreground opacity-0 group-has-checked:opacity-100" />
      </span>
      {/* подпись это и имя галочки для экранного диктора */}
      <span className="block truncate px-2 py-1.5 text-xs text-muted-foreground">
        {[when, media.caption].filter(Boolean).join(" · ") || t("untitled")}
      </span>
    </label>
  );
}

/** Миниатюра Meta: пока грузится, на её месте пульсирует скелет, потом она проявляется.
 * Не next/image: ссылка Meta подписана и временная, оптимизатору её не кешировать. */
function Thumbnail({
  src,
  alt,
  lazy = false,
  className,
}: {
  src: string;
  alt: string;
  lazy?: boolean;
  className?: string;
}) {
  const [state, setState] = useState<"loading" | "loaded" | "failed">("loading");

  return (
    <div
      className={cn("overflow-hidden bg-muted", state === "loading" && "animate-pulse", className)}
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={src}
        alt={alt}
        loading={lazy ? "lazy" : undefined}
        referrerPolicy="no-referrer"
        onLoad={() => setState("loaded")}
        onError={() => setState("failed")}
        className={cn(
          "size-full object-cover transition-opacity duration-200",
          state === "loaded" ? "opacity-100" : "opacity-0",
        )}
      />
    </div>
  );
}

"use client";

import { CircleCheck, CircleX, RotateCw } from "lucide-react";
import { useRouter } from "next/navigation";
import { useFormatter, useTranslations } from "next-intl";
import { startTransition, useState, useTransition } from "react";

import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { useInBrowser } from "@/hooks/use-in-browser";
import type { MetaApp, WebhookCheck } from "@/lib/meta-app";
import { cn } from "@/lib/utils";

import { checkWebhook } from "../actions";

/** Проверка вебхука в два шага: виден ли адрес из интернета и подтвердила ли его Meta. */
export function WebhookStatus({ metaApp }: { metaApp: MetaApp | null }) {
  const t = useTranslations("MetaApp.webhook");

  return (
    <>
      {!metaApp && <p className="text-sm text-muted-foreground">{t("pending")}</p>}
      <Step title={t("reachTitle")} description={t("reachDescription")}>
        <ReachCheck disabled={!metaApp} />
      </Step>
      <Separator />
      <Step title={t("metaTitle")}>
        <MetaVerified metaApp={metaApp} />
      </Step>
    </>
  );
}

function Step({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="grid gap-3">
      <div className="grid gap-1">
        <h3 className="font-medium">{title}</h3>
        {description && <p className="text-sm text-muted-foreground">{description}</p>}
      </div>
      {children}
    </section>
  );
}

/** Самопроверка: api стучится на свой адрес вебхука и ждёт свой же ответ. */
function ReachCheck({ disabled }: { disabled: boolean }) {
  const t = useTranslations("MetaApp.webhook");
  const [result, setResult] = useState<WebhookCheck | null>(null);
  const [pending, startChecking] = useTransition();

  function check() {
    startChecking(async () => {
      const next = await checkWebhook();
      // после await обновление уже вне перехода: оборачиваем заново
      startTransition(() => setResult(next));
    });
  }

  return (
    <div className="flex flex-wrap items-center gap-4">
      <Button type="button" variant="outline" disabled={disabled || pending} onClick={check}>
        {t("check")}
      </Button>
      {result &&
        (result.ok ? (
          <p className="flex items-center gap-2 text-sm">
            <CircleCheck className="size-4 shrink-0 text-brand" />
            {t("ok")}
          </p>
        ) : (
          <p role="alert" className="flex items-center gap-2 text-sm text-destructive">
            <CircleX className="size-4 shrink-0" />
            {t(`errors.${result.error ?? "unreachable"}`)}
          </p>
        ))}
    </div>
  );
}

/** Статус от Meta: время, когда она последний раз проверила адрес нашим маркером.
 * Meta проверяет из своего кабинета, нам об этом не сообщают: статус обновляет кнопка. */
function MetaVerified({ metaApp }: { metaApp: MetaApp | null }) {
  const t = useTranslations("MetaApp.webhook");
  const format = useFormatter();
  const inBrowser = useInBrowser();
  const router = useRouter();
  const [pending, startRefresh] = useTransition();
  const verifiedAt = metaApp?.webhook_verified_at;

  let status: React.ReactNode;
  if (!verifiedAt) {
    status = <p className="text-sm text-muted-foreground">{t("notVerified")}</p>;
  } else if (!inBrowser) {
    // до гидрации пояс браузера неизвестен: держим место под строку
    status = <Skeleton className="h-5 w-64" />;
  } else {
    status = (
      <p className="flex items-center gap-2 text-sm">
        <CircleCheck className="size-4 shrink-0 text-brand" />
        {t("verified", {
          date: format.dateTime(new Date(verifiedAt), { dateStyle: "medium", timeStyle: "short" }),
        })}
      </p>
    );
  }

  return (
    <div className="flex items-center justify-between gap-4">
      {status}
      <Button
        type="button"
        // как кнопка копирования у строк выше: высота как у Input
        variant="outline"
        size="icon"
        className="size-10 shrink-0 md:size-9"
        aria-label={t("refresh")}
        disabled={!metaApp || pending}
        // страница перезапрашивает данные у сервера, состояние на ней не теряется
        onClick={() => startRefresh(() => router.refresh())}
      >
        <RotateCw className={cn(pending && "animate-spin")} />
      </Button>
    </div>
  );
}

export function WebhookStatusSkeleton() {
  return (
    <>
      {[0, 1].map((i) => (
        <div key={i} className="grid gap-3">
          <div className="grid gap-1">
            <Skeleton className="h-5 w-48" />
            <Skeleton className="h-4 w-full max-w-md" />
          </div>
          <Skeleton className="h-10 w-28 md:h-9" />
        </div>
      ))}
    </>
  );
}

"use client";

import { RefreshCw } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useTransition } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** Перечитать ленту с сервера. Автообновления пока нет: лента по кнопке. */
export function RefreshButton() {
  const t = useTranslations("Inbox");
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  return (
    <Button
      variant="outline"
      disabled={pending}
      onClick={() => startTransition(() => router.refresh())}
    >
      <RefreshCw className={cn(pending && "animate-spin")} />
      {t("refresh")}
    </Button>
  );
}

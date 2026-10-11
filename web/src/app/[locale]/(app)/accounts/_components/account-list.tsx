"use client";

import { useFormatter, useTranslations } from "next-intl";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Skeleton } from "@/components/ui/skeleton";
import { useInBrowser } from "@/hooks/use-in-browser";
import type { Account } from "@/lib/accounts";
import { cn } from "@/lib/utils";

export function AccountList({ accounts }: { accounts: Account[] }) {
  const t = useTranslations("Accounts");
  const format = useFormatter();
  const inBrowser = useInBrowser();

  if (accounts.length === 0) {
    return <p className="text-sm text-muted-foreground">{t("empty")}</p>;
  }
  return (
    <ul className="grid divide-y">
      {accounts.map((account) => (
        <li key={account.id} className="flex items-center gap-3 py-3 first:pt-0 last:pb-0">
          <Avatar>
            <AvatarFallback>{account.username.slice(0, 2).toUpperCase()}</AvatarFallback>
          </Avatar>
          <div className="grid min-w-0 flex-1 gap-0.5">
            <span className="truncate font-medium">@{account.username}</span>
            {/* дата в поясе браузера: до гидрации держим место */}
            {inBrowser ? (
              <span className="text-xs text-muted-foreground">
                {t("connectedAt", {
                  date: format.dateTime(new Date(account.connected_at), { dateStyle: "medium" }),
                })}
              </span>
            ) : (
              <Skeleton className="h-4 w-40" />
            )}
          </div>
          <span
            className={cn(
              "rounded-full border px-2 py-0.5 text-xs",
              account.status === "active" ? "border-brand/30 text-brand" : "text-muted-foreground",
            )}
          >
            {t(`status.${account.status}`)}
          </span>
        </li>
      ))}
    </ul>
  );
}

export function AccountListSkeleton() {
  return (
    <div className="flex items-center gap-3">
      <Skeleton className="size-8 rounded-full" />
      <div className="grid flex-1 gap-1">
        <Skeleton className="h-5 w-40" />
        <Skeleton className="h-4 w-32" />
      </div>
    </div>
  );
}

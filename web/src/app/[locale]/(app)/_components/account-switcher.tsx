"use client";

import { Check, ChevronsUpDown, Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import { useTransition } from "react";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { SidebarMenu, SidebarMenuButton, SidebarMenuItem } from "@/components/ui/sidebar";
import { Link } from "@/i18n/navigation";
import type { Account } from "@/lib/accounts";

import { selectAccount } from "../actions";

// в браузер только то, что нужно меню: без id в Instagram и дат
type Item = Pick<Account, "id" | "username" | "status">;
type Props = { accounts: Item[]; currentId: string | null };

/** Шапка меню: какой аккаунт Instagram сейчас настраиваем. Как переключатель
 * организаций у Dokploy. */
export function AccountSwitcher({ accounts, currentId }: Props) {
  const t = useTranslations("App.account");
  const [pending, startTransition] = useTransition();
  const current = accounts.find((a) => a.id === currentId);

  if (!current) {
    return (
      <SidebarMenu>
        <SidebarMenuItem>
          <SidebarMenuButton size="lg" render={<Link href="/accounts" />}>
            <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border">
              <Plus className="size-4" />
            </span>
            <span className="truncate font-medium">{t("none")}</span>
          </SidebarMenuButton>
        </SidebarMenuItem>
      </SidebarMenu>
    );
  }

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger render={<SidebarMenuButton size="lg" aria-busy={pending} />}>
            <AccountAvatar username={current.username} />
            <div className="grid flex-1 text-left text-sm leading-tight">
              <span className="truncate font-medium">@{current.username}</span>
              <Status status={current.status} />
            </div>
            <ChevronsUpDown className="ml-auto" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-(--anchor-width) min-w-56">
            <DropdownMenuGroup>
              <DropdownMenuLabel>{t("label")}</DropdownMenuLabel>
              {accounts.map((account) => (
                <DropdownMenuItem
                  key={account.id}
                  onClick={() => startTransition(() => selectAccount(account.id))}
                >
                  <AccountAvatar username={account.username} small />
                  <span className="truncate">@{account.username}</span>
                  {account.id === current.id && <Check className="ml-auto" />}
                </DropdownMenuItem>
              ))}
            </DropdownMenuGroup>
            <DropdownMenuSeparator />
            <DropdownMenuItem render={<Link href="/accounts" />}>
              <Plus />
              {t("connect")}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}

function AccountAvatar({ username, small }: { username: string; small?: boolean }) {
  // аватарку из Instagram добавим позже: ссылки на неё у Meta временные
  return (
    <Avatar className={small ? "size-6 rounded-md" : "size-8 rounded-lg"}>
      <AvatarFallback className={small ? "rounded-md text-xs" : "rounded-lg"}>
        {username.slice(0, 1).toUpperCase()}
      </AvatarFallback>
    </Avatar>
  );
}

function Status({ status }: { status: Item["status"] }) {
  const t = useTranslations("App.account");
  if (status === "token_expired") {
    return <span className="truncate text-xs text-destructive">{t("reconnect")}</span>;
  }
  return <span className="truncate text-xs text-muted-foreground">{t("instagram")}</span>;
}

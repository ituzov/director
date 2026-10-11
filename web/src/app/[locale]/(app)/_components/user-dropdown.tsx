"use client";

import { ChevronsUpDown, LogOut } from "lucide-react";
import { useTranslations } from "next-intl";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { SidebarMenu, SidebarMenuButton, SidebarMenuItem } from "@/components/ui/sidebar";
import { logout } from "@/lib/logout";

type Props = { email: string; role: "owner" | "member" };

export function UserDropdown({ email, role }: Props) {
  const t = useTranslations("App");
  // имени у пользователя пока нет, инициалы из почты
  const initials = email.slice(0, 2).toUpperCase();

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger render={<SidebarMenuButton size="lg" />}>
            <Avatar className="size-8 rounded-lg">
              <AvatarFallback className="rounded-lg">{initials}</AvatarFallback>
            </Avatar>
            <div className="grid flex-1 text-left text-sm leading-tight">
              <span className="truncate font-medium">{email}</span>
              <span className="truncate text-xs text-muted-foreground">{t(`roles.${role}`)}</span>
            </div>
            <ChevronsUpDown className="ml-auto" />
          </DropdownMenuTrigger>
          {/* над строкой пользователя, шириной с неё (--anchor-width задаёт Base UI) */}
          <DropdownMenuContent side="top" align="start" className="w-(--anchor-width) min-w-56">
            <DropdownMenuItem onClick={() => logout()}>
              <LogOut />
              {t("logout")}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}

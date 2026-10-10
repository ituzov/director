"use client";

import { LayoutDashboard } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { Link, usePathname } from "@/i18n/navigation";

// разделы добавляются сюда по мере появления страниц
const ITEMS = [{ href: "/", key: "overview", icon: LayoutDashboard }] as const;

export function NavMain() {
  const t = useTranslations("App.nav");
  const pathname = usePathname();

  return (
    <SidebarGroup>
      <SidebarGroupContent>
        <SidebarMenu>
          {ITEMS.map(({ href, key, icon: Icon }) => (
            <SidebarMenuItem key={href}>
              <SidebarMenuButton
                isActive={pathname === href}
                tooltip={t(key)}
                render={<Link href={href} />}
              >
                <Icon />
                <span>{t(key)}</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          ))}
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  );
}

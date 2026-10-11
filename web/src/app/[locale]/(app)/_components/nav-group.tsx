"use client";

import { KeyRound, LayoutDashboard } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { Link, usePathname } from "@/i18n/navigation";

// Пункты по группам: пункт появляется вместе со своей страницей.
// Здесь, а не на сервере: иконки это компоненты, через границу в браузер их не передать
const GROUPS = {
  work: [{ href: "/", key: "overview", icon: LayoutDashboard }],
  settings: [{ href: "/settings/meta", key: "metaApp", icon: KeyRound }],
} as const;

export function NavGroup({ group }: { group: keyof typeof GROUPS }) {
  const t = useTranslations("App.nav");
  const pathname = usePathname();

  return (
    <SidebarGroup>
      <SidebarGroupLabel>{t(`groups.${group}`)}</SidebarGroupLabel>
      <SidebarGroupContent>
        <SidebarMenu>
          {GROUPS[group].map(({ href, key, icon: Icon }) => (
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

/** Подпись текущей страницы для верхней полосы: та же, что у пункта меню. */
export function CurrentPageTitle() {
  const t = useTranslations("App.nav");
  const pathname = usePathname();
  // самый длинный подходящий адрес: /settings/meta/x всё ещё «Приложение Meta»
  const item = Object.values(GROUPS)
    .flat()
    .filter(({ href }) => pathname === href || (href !== "/" && pathname.startsWith(`${href}/`)))
    .sort((a, b) => b.href.length - a.href.length)[0];

  // h1 страницы: заголовки панелей на ней h2
  return item ? (
    <h1 className="truncate text-sm font-normal text-muted-foreground">{t(item.key)}</h1>
  ) : null;
}

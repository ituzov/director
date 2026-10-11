"use client";

import { AtSign, KeyRound, LayoutDashboard } from "lucide-react";
import { useTranslations } from "next-intl";
import { Suspense } from "react";

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
  work: [
    { href: "/", key: "overview", icon: LayoutDashboard },
    { href: "/accounts", key: "accounts", icon: AtSign },
  ],
  settings: [{ href: "/settings/meta", key: "metaApp", icon: KeyRound }],
} as const;

/** Пункт меню, в чьём разделе мы сейчас: самый длинный подходящий адрес,
 * /autoreplies/123 и /settings/meta/x тоже считаются своими разделами. */
function currentItem(pathname: string) {
  return Object.values(GROUPS)
    .flat()
    .filter(({ href }) => pathname === href || (href !== "/" && pathname.startsWith(`${href}/`)))
    .sort((a, b) => b.href.length - a.href.length)[0];
}

/** Группа меню. Адрес страницы с параметром (/autoreplies/[id]) при сборке не
 * известен, а каркас собирается заранее: пока адреса нет, показываем ту же группу
 * без подсветки, подсветка доезжает потоком. Без Suspense сборка падает. */
export function NavGroup({ group }: { group: keyof typeof GROUPS }) {
  return (
    <Suspense fallback={<NavGroupItems group={group} activeHref={null} />}>
      <ActiveNavGroup group={group} />
    </Suspense>
  );
}

function ActiveNavGroup({ group }: { group: keyof typeof GROUPS }) {
  const pathname = usePathname();
  return <NavGroupItems group={group} activeHref={currentItem(pathname)?.href ?? null} />;
}

function NavGroupItems({
  group,
  activeHref,
}: {
  group: keyof typeof GROUPS;
  activeHref: string | null;
}) {
  const t = useTranslations("App.nav");

  return (
    <SidebarGroup>
      <SidebarGroupLabel>{t(`groups.${group}`)}</SidebarGroupLabel>
      <SidebarGroupContent>
        {/* у shadcn пункты вплотную: подсвеченные соседи слипались в одну плашку */}
        <SidebarMenu className="gap-1">
          {GROUPS[group].map(({ href, key, icon: Icon }) => (
            <SidebarMenuItem key={href}>
              <SidebarMenuButton
                isActive={href === activeHref}
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

/** Подпись текущей страницы для верхней полосы: та же, что у пункта меню.
 * Тоже из адреса, поэтому в Suspense; полоса фиксированной высоты, ничего не прыгает. */
export function CurrentPageTitle() {
  return (
    <Suspense>
      <PageTitle />
    </Suspense>
  );
}

function PageTitle() {
  const t = useTranslations("App.nav");
  const item = currentItem(usePathname());
  // h1 страницы: заголовки панелей на ней h2
  return item ? (
    <h1 className="truncate text-sm font-normal text-muted-foreground">{t(item.key)}</h1>
  ) : null;
}

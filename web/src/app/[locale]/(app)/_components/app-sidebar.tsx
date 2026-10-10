import { useTranslations } from "next-intl";
import { Suspense } from "react";

import { Logo } from "@/components/logo";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarMenuSkeleton,
  SidebarRail,
} from "@/components/ui/sidebar";
import { getCurrentUser } from "@/lib/session";
import { APP_VERSION } from "@/lib/version";

import { NavGroup } from "./nav-group";
import { UserDropdown } from "./user-dropdown";

export function AppSidebar() {
  const t = useTranslations("Auth");
  const tApp = useTranslations("App");

  return (
    <Sidebar variant="floating" collapsible="icon">
      <SidebarHeader>
        <div className="flex items-center gap-2 p-1 group-data-[collapsible=icon]:p-0">
          <Logo className="size-8" />
          <span className="font-display text-base group-data-[collapsible=icon]:hidden">
            {t("name")}
          </span>
        </div>
      </SidebarHeader>
      <SidebarContent>
        <NavGroup group="work" />
        {/* без заглушки: участнику скелет показал бы группу, которой у него нет */}
        <Suspense>
          <NavSettings />
        </Suspense>
      </SidebarContent>
      <SidebarFooter>
        {/* пользователь зависит от сессии: в оболочке скелет, сам блок приезжает потоком */}
        <Suspense fallback={<SidebarMenuSkeleton showIcon />}>
          <UserMenu />
        </Suspense>
        <p className="text-muted-foreground text-center text-xs group-data-[collapsible=icon]:hidden">
          {tApp("version", { version: APP_VERSION })}
        </p>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}

/** Настройки видит только владелец. Читает сессию, поэтому живёт только внутри Suspense. */
async function NavSettings() {
  const user = await getCurrentUser();
  return user.role === "owner" ? <NavGroup group="settings" /> : null;
}

/** Кто вошёл. Читает сессию, поэтому живёт только внутри Suspense. */
async function UserMenu() {
  const user = await getCurrentUser();
  // в браузер только то, что нужно меню: не весь объект пользователя
  return <UserDropdown email={user.email} role={user.role} />;
}

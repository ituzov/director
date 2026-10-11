import { useTranslations } from "next-intl";
import { Suspense } from "react";

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarRail,
} from "@/components/ui/sidebar";
import { getCurrentAccount, getSwitchableAccounts } from "@/lib/current-account";
import { getCurrentUser } from "@/lib/session";
import { APP_VERSION } from "@/lib/version";

import { AccountSwitcher } from "./account-switcher";
import { NavGroup } from "./nav-group";
import { ProfileSkeleton } from "./profile-skeleton";
import { UserDropdown } from "./user-dropdown";

export function AppSidebar() {
  const tApp = useTranslations("App");

  return (
    <Sidebar variant="floating" collapsible="icon">
      <SidebarHeader>
        {/* аккаунты приходят из api: в оболочке скелет, сам переключатель потоком */}
        <Suspense fallback={<ProfileSkeleton />}>
          <AccountMenu />
        </Suspense>
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
        <Suspense fallback={<ProfileSkeleton />}>
          <UserMenu />
        </Suspense>
        <p className="text-center text-xs text-muted-foreground group-data-[collapsible=icon]:hidden">
          {tApp("version", { version: APP_VERSION })}
        </p>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}

/** Какой аккаунт настраиваем. Ходит в api, поэтому живёт только внутри Suspense. */
async function AccountMenu() {
  const [accounts, current] = await Promise.all([getSwitchableAccounts(), getCurrentAccount()]);
  return (
    <AccountSwitcher
      accounts={accounts.map(({ id, username, status }) => ({ id, username, status }))}
      currentId={current?.id ?? null}
    />
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

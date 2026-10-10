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
import { APP_VERSION } from "@/lib/version";

import { NavMain } from "./nav-main";
import { UserMenu } from "./user-menu";

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
        <NavMain />
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

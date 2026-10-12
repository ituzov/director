import { useTranslations } from "next-intl";

import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { Separator } from "@/components/ui/separator";
import { TooltipProvider } from "@/components/ui/tooltip";

import { AppSidebar } from "./_components/app-sidebar";
import { CurrentPageTitle } from "./_components/nav-group";

/**
 * Каркас админки: меню слева, контент справа. Сессию здесь не читаем:
 * layout уходит в статическую оболочку, пользователь подгружается в Suspense внутри.
 * Состояние «свёрнут» не запоминаем: его cookie пришлось бы читать здесь же.
 */
export default function AppLayout({ children }: LayoutProps<"/[locale]">) {
  const t = useTranslations("App");
  return (
    <TooltipProvider>
      <SidebarProvider>
        <AppSidebar />
        <SidebarInset>
          <header className="flex h-14 shrink-0 items-center gap-2 border-b px-4">
            <SidebarTrigger aria-label={t("sidebar.toggle")} />
            <Separator orientation="vertical" className="my-4" />
            <CurrentPageTitle />
          </header>
          <div className="flex-1 p-4 md:p-6">{children}</div>
        </SidebarInset>
      </SidebarProvider>
    </TooltipProvider>
  );
}

import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

type PageProps = {
  // narrow для форм и списков, wide для таблиц и графиков
  width?: "narrow" | "wide";
  children: React.ReactNode;
};

/** Колонка страницы админки: панели друг под другом. */
export function Page({ width = "narrow", children }: PageProps) {
  return (
    <div className={cn("mx-auto grid w-full gap-6", width === "narrow" && "max-w-5xl")}>
      {children}
    </div>
  );
}

type PanelProps = {
  icon?: LucideIcon;
  title: string;
  description?: string;
  // главная кнопка панели, справа в шапке
  actions?: React.ReactNode;
  children: React.ReactNode;
};

/**
 * Одна задача на странице: рамка, карточка, шапка с иконкой и разделитель.
 * Заголовок h2: h1 у страницы один, это подпись в верхней полосе.
 */
export function Panel({ icon: Icon, title, description, actions, children }: PanelProps) {
  return (
    <div className="bg-muted/40 rounded-2xl border p-1.5">
      <section className="bg-card text-card-foreground rounded-xl border shadow-sm">
        <header className="flex flex-wrap items-start justify-between gap-4 border-b p-4 md:p-6">
          <div className="grid gap-1">
            <h2 className="flex items-center gap-2 text-xl font-semibold">
              {Icon && <Icon className="text-muted-foreground size-5" />}
              {title}
            </h2>
            {description && <p className="text-muted-foreground text-sm">{description}</p>}
          </div>
          {actions}
        </header>
        <div className="grid gap-4 p-4 md:gap-6 md:p-6">{children}</div>
      </section>
    </div>
  );
}

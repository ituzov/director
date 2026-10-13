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
  // строка или разметка: в описании бывает ссылка
  description?: React.ReactNode;
  // главная кнопка панели, справа в шапке
  actions?: React.ReactNode;
  // sm: подсобная панель (превью): шапка в одну строку, отступы меньше
  size?: "default" | "sm";
  children: React.ReactNode;
};

/**
 * Одна задача на странице: рамка, карточка, шапка с иконкой и разделитель.
 * Заголовок h2: h1 у страницы один, это подпись в верхней полосе.
 */
export function Panel({
  icon: Icon,
  title,
  description,
  actions,
  size = "default",
  children,
}: PanelProps) {
  const sm = size === "sm";
  return (
    <div className="rounded-2xl border bg-muted/40 p-1.5">
      <section className="rounded-xl border bg-card text-card-foreground shadow-sm">
        <header
          className={cn(
            "flex flex-wrap items-start justify-between gap-4 border-b",
            sm ? "px-4 py-3" : "p-4 md:p-6",
          )}
        >
          <div className="grid gap-1">
            <h2
              className={cn(
                "flex items-center gap-2",
                sm ? "text-sm font-medium" : "text-xl font-semibold",
              )}
            >
              {Icon && <Icon className="size-5 text-muted-foreground" />}
              {title}
            </h2>
            {description && <p className="text-sm text-muted-foreground">{description}</p>}
          </div>
          {actions}
        </header>
        <div className={cn("grid gap-4 p-4", !sm && "md:gap-6 md:p-6")}>{children}</div>
      </section>
    </div>
  );
}

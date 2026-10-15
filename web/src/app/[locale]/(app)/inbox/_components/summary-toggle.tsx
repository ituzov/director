import { ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";

import type { Summary } from "@/lib/inbox";
import { cn } from "@/lib/utils";

export type Toggle = { open: boolean; controls: string; onClick: () => void };

/** Итог выдачи кнопкой: раскрывает шаги. Цвет берёт у родителя. */
export function SummaryToggle({
  result,
  toggle,
  className,
}: {
  result: Summary;
  toggle: Toggle;
  className?: string;
}) {
  const t = useTranslations("Inbox");
  return (
    <button
      type="button"
      aria-expanded={toggle.open}
      aria-controls={toggle.controls}
      onClick={toggle.onClick}
      className={cn(
        // под палец: на телефоне 40px, от md 36px
        "inline-flex min-h-10 items-center gap-0.5 rounded-sm hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none md:min-h-9",
        className,
      )}
    >
      {t(`summary.${result}`)}
      <ChevronRight
        className={cn("size-4 shrink-0 transition-transform", toggle.open && "rotate-90")}
      />
    </button>
  );
}

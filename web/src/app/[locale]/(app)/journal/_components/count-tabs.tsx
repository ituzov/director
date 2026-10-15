import { Link } from "@/i18n/navigation";
import { cn } from "@/lib/utils";

export type CountTab = {
  key: string;
  href: string;
  label: string;
  count: number;
  current: boolean;
};

/** Вкладки текстом с подчёркиванием и счётчиком: этапы «Выдач» и итоги «Всех событий».
 * Вкладка в адресе: ссылки, а не кнопки. */
export function CountTabs({ label, tabs }: { label: string; tabs: CountTab[] }) {
  return (
    <nav aria-label={label} className="flex gap-5 overflow-x-auto border-b">
      {tabs.map((tab) => (
        <Link
          key={tab.key}
          href={tab.href}
          aria-current={tab.current ? "page" : undefined}
          className={cn(
            // под палец: 40px на телефоне, 36px от md
            "-mb-px inline-flex h-10 shrink-0 items-center gap-1.5 border-b-2 border-transparent text-sm whitespace-nowrap text-muted-foreground transition-colors hover:text-foreground md:h-9",
            tab.current && "border-foreground text-foreground",
          )}
        >
          {tab.label}
          <span className="font-mono text-xs tabular-nums">{tab.count}</span>
        </Link>
      ))}
    </nav>
  );
}

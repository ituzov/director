import { useTranslations } from "next-intl";

import { Link } from "@/i18n/navigation";
import { type StageCounts, type Tab, TAB_KEYS, tabCount } from "@/lib/deliveries";
import { cn } from "@/lib/utils";

/** Вкладки этапов со счётчиками: кто сейчас на каком шаге. Вкладка в адресе. */
export function DeliveryTabs({ tab, counts }: { tab: Tab; counts: StageCounts }) {
  const t = useTranslations("Inbox.tabs");
  return (
    <nav aria-label={t("label")} className="flex gap-5 overflow-x-auto border-b">
      {TAB_KEYS.map((key) => (
        <Link
          key={key}
          href={key === "all" ? "/inbox" : `/inbox?tab=${key}`}
          aria-current={tab === key ? "page" : undefined}
          className={cn(
            // под палец: 40px на телефоне, 36px от md
            "-mb-px inline-flex h-10 shrink-0 items-center gap-1.5 border-b-2 border-transparent text-sm whitespace-nowrap text-muted-foreground transition-colors hover:text-foreground md:h-9",
            tab === key && "border-foreground text-foreground",
          )}
        >
          {t(key)}
          <span className="font-mono text-xs tabular-nums">{tabCount(key, counts)}</span>
        </Link>
      ))}
    </nav>
  );
}

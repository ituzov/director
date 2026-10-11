import { useTranslations } from "next-intl";

import { Link } from "@/i18n/navigation";
import { cn } from "@/lib/utils";

/** Активные и архив. Вкладка в адресе: обновление страницы её не сбрасывает. */
export function ArchiveTabs({ archived }: { archived: boolean }) {
  const t = useTranslations("Autoreplies.tabs");
  const tabs = [
    { key: "active", href: "/autoreplies", current: !archived },
    { key: "archive", href: "/autoreplies?archived=1", current: archived },
  ] as const;

  return (
    <nav className="inline-flex w-fit rounded-lg border bg-muted/40 p-0.5">
      {tabs.map(({ key, href, current }) => (
        <Link
          key={key}
          href={href}
          aria-current={current ? "page" : undefined}
          className={cn(
            "rounded-md px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground",
            current && "bg-background text-foreground shadow-sm",
          )}
        >
          {t(key)}
        </Link>
      ))}
    </nav>
  );
}

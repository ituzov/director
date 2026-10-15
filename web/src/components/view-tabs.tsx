import { Link } from "@/i18n/navigation";
import { cn } from "@/lib/utils";

export type ViewTab = { key: string; href: string; label: string; current: boolean };

/** Переключатель вида страницы. Вид в адресе: обновление и «назад» его не сбрасывают,
 * сервер сразу рисует нужный список. */
export function ViewTabs({ tabs, label }: { tabs: ViewTab[]; label: string }) {
  return (
    <nav aria-label={label} className="inline-flex w-fit rounded-lg border bg-muted/40 p-0.5">
      {tabs.map(({ key, href, label, current }) => (
        <Link
          key={key}
          href={href}
          aria-current={current ? "page" : undefined}
          className={cn(
            // под палец: 40px на телефоне, 36px от md
            "inline-flex h-10 items-center rounded-md px-3 text-sm text-muted-foreground transition-colors hover:text-foreground md:h-9",
            current && "bg-background text-foreground shadow-sm",
          )}
        >
          {label}
        </Link>
      ))}
    </nav>
  );
}

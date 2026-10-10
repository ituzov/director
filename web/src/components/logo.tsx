import { cn } from "@/lib/utils";

/**
 * Знак Директора: буква Д из Unbounded 800, левая ножка стала хвостиком сообщения.
 * Контур в единицах шрифта (1000 на кегль), перевёрнут: у шрифта ось y смотрит вверх.
 * viewBox с запасом и смещён вверх, чтобы буква в квадрате сидела чуть ниже центра.
 */
export function Logo({ className }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        "flex size-10 shrink-0 items-center justify-center rounded-lg bg-brand text-brand-foreground",
        className,
      )}
    >
      <svg viewBox="-532 -615 2100 2100" className="size-full">
        <path
          transform="matrix(1 0 0 -1 0 750)"
          fill="currentColor"
          d="M20.4 0V205.6H196.8L258.8 203.6H767.2L826.2 205.6H1054.6V-150H836.4V0H238.6L-20 -240ZM173.4 750H925.8V59.8H693V652.4L797.8 547.6H297.2L391.8 625.6Q400.8 582.6 402.4 543Q404 503.4 404 468.2Q404 353.4 382.8 276.4Q361.6 199.4 319 160.8Q276.4 122.2 212 122.2L114.6 202Q152.4 248 170.7 325.8Q189 403.6 189 516.6Q189 569.6 185 627.6Q181 685.6 173.4 750Z"
        />
      </svg>
    </span>
  );
}

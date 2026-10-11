import { Skeleton } from "@/components/ui/skeleton";

/** Заглушка большой строки меню (аккаунт сверху, пользователь снизу) той же высоты,
 * что и сама строка: стандартный скелет пункта ниже, и меню прыгало при загрузке. */
export function ProfileSkeleton() {
  return (
    <div className="flex h-12 items-center gap-2 p-2 group-data-[collapsible=icon]:p-0">
      <Skeleton className="size-8 shrink-0 rounded-lg" />
      <div className="grid flex-1 gap-1.5 group-data-[collapsible=icon]:hidden">
        <Skeleton className="h-3.5 w-28" />
        <Skeleton className="h-3 w-16" />
      </div>
    </div>
  );
}

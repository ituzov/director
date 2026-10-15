import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";

/** «Показать ещё» под списком и ошибка догрузки. */
export function MoreButton({
  pending,
  failed,
  onClick,
}: {
  pending: boolean;
  failed: boolean;
  onClick: () => void;
}) {
  const t = useTranslations("Inbox");
  return (
    <div className="grid justify-items-center gap-2">
      <Button variant="outline" disabled={pending} onClick={onClick}>
        {t("more")}
      </Button>
      {failed && (
        <p role="alert" className="text-sm text-destructive">
          {t("moreFailed")}
        </p>
      )}
    </div>
  );
}

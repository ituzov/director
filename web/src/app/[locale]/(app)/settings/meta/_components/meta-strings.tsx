import { useTranslations } from "next-intl";

import { CopyField } from "@/components/copy-field";
import { Skeleton } from "@/components/ui/skeleton";
import type { MetaApp } from "@/lib/meta-app";

const FIELDS = ["webhookUrl", "verifyToken", "redirectUri", "privacyUrl"] as const;

/** Строки, которые владелец переносит в кабинет Meta, каждая со своим местом.
 * До первого сохранения ключей видны, но выключены: маркер рождается при сохранении,
 * а человек уже видит, что его ждёт дальше. */
export function MetaStrings({ metaApp }: { metaApp: MetaApp | null }) {
  const t = useTranslations("MetaApp.strings");
  const values = {
    webhookUrl: metaApp?.webhook_url,
    verifyToken: metaApp?.verify_token,
    redirectUri: metaApp?.redirect_uri,
    privacyUrl: metaApp?.privacy_url,
  };

  return (
    <>
      {!metaApp && <p className="text-muted-foreground text-sm">{t("pending")}</p>}
      {/* без PUBLIC_URL api не знает, по какому адресу его видит Meta */}
      {metaApp && !metaApp.webhook_url && (
        <p className="text-muted-foreground text-sm">{t("noPublicUrl")}</p>
      )}
      {FIELDS.map((field) => (
        <CopyField
          key={field}
          label={t(field)}
          value={values[field] ?? undefined}
          hint={t(`${field}Hint`)}
        />
      ))}
    </>
  );
}

export function MetaStringsSkeleton() {
  return FIELDS.map((field) => (
    <div key={field} className="grid gap-2">
      <Skeleton className="h-4 w-36" />
      <div className="flex gap-2">
        <Skeleton className="h-10 w-full md:h-9" />
        <Skeleton className="size-10 shrink-0 md:size-9" />
      </div>
      <Skeleton className="h-3 w-64 max-w-full" />
    </div>
  ));
}

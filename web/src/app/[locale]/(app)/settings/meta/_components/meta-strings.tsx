import { Link2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { CopyField } from "@/components/copy-field";
import { Panel } from "@/components/page";
import type { MetaApp } from "@/lib/meta-app";

/** Строки, которые владелец переносит в кабинет Meta, каждая со своим местом. */
export function MetaStrings({ metaApp }: { metaApp: MetaApp }) {
  const t = useTranslations("MetaApp.strings");
  const { webhook_url, verify_token, redirect_uri, privacy_url } = metaApp;

  return (
    <Panel icon={Link2} title={t("title")} description={t("description")}>
      {webhook_url && (
        <CopyField label={t("webhookUrl")} value={webhook_url} hint={t("webhookUrlHint")} />
      )}
      <CopyField label={t("verifyToken")} value={verify_token} hint={t("verifyTokenHint")} />
      {redirect_uri && (
        <CopyField label={t("redirectUri")} value={redirect_uri} hint={t("redirectUriHint")} />
      )}
      {privacy_url && (
        <CopyField label={t("privacyUrl")} value={privacy_url} hint={t("privacyUrlHint")} />
      )}
      {/* без PUBLIC_URL api не знает, по какому адресу его видит Meta */}
      {!webhook_url && <p className="text-muted-foreground text-sm">{t("noPublicUrl")}</p>}
    </Panel>
  );
}

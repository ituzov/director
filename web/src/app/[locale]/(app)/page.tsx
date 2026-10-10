import { useTranslations } from "next-intl";

export default function OverviewPage() {
  const t = useTranslations("App.overview");

  return (
    <div className="grid gap-2">
      <h1 className="text-2xl font-semibold">{t("title")}</h1>
      <p className="text-muted-foreground text-sm">{t("empty")}</p>
    </div>
  );
}

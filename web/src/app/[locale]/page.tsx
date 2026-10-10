import { useTranslations } from "next-intl";

export default function HomePage() {
  const t = useTranslations("Home");
  return (
    <main className="flex flex-1 items-center justify-center">
      <h1 className="font-display text-3xl">{t("title")}</h1>
    </main>
  );
}

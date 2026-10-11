import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { Logo } from "@/components/logo";

// страницу открывают Meta и подписчики откуда угодно: всегда по-английски
const LOCALE = "en";

// deletion последним: на него ведёт якорь для кабинета Meta
const SECTIONS = ["data", "purpose", "storage", "retention", "sharing", "deletion"] as const;

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations({ locale: LOCALE, namespace: "Privacy" });
  return { title: t("title") };
}

export default async function PrivacyPage() {
  const t = await getTranslations({ locale: LOCALE, namespace: "Privacy" });

  return (
    <main className="px-4 py-10">
      {/* у <html> язык из cookie, а текст здесь всегда английский */}
      <article lang="en" className="mx-auto grid max-w-2xl gap-8">
        <header className="flex items-center gap-3">
          <Logo />
          <h1 className="text-2xl font-semibold">{t("title")}</h1>
        </header>

        <p className="leading-relaxed">{t("intro")}</p>

        {SECTIONS.map((key) => (
          <section key={key} id={key} className="grid scroll-mt-10 gap-2">
            <h2 className="text-lg font-semibold">{t(`${key}.title`)}</h2>
            <p className="leading-relaxed text-muted-foreground">{t(`${key}.body`)}</p>
          </section>
        ))}
      </article>
    </main>
  );
}

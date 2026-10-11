import { useTranslations } from "next-intl";

import { Logo } from "@/components/logo";
import { APP_VERSION } from "@/lib/version";

type Props = { title: string; description: string; children: React.ReactNode };

/** Рамка входа и регистрации: слева о продукте (с lg), справа заголовок и форма. */
export function AuthShell({ title, description, children }: Props) {
  const t = useTranslations("Auth");

  return (
    <div className="grid min-h-dvh lg:grid-cols-2">
      <aside className="hidden flex-col justify-between bg-brand p-10 text-brand-foreground lg:flex">
        <div className="flex items-center gap-3">
          <Logo className="bg-brand-foreground text-brand" />
          <span className="font-display text-xl">{t("name")}</span>
        </div>
        <p className="max-w-xl font-display text-3xl leading-tight text-balance text-brand-foreground/60 xl:text-4xl">
          {t.rich("tagline", {
            // каждая половина фразы со своей строки, внутри строки браузер выравнивает сам
            line: (chunks) => <span className="block">{chunks}</span>,
            hl: (chunks) => <span className="text-brand-foreground">{chunks}</span>,
          })}
        </p>
        <div className="flex gap-4 font-mono text-xs opacity-70">
          <span>{APP_VERSION}</span>
          <a
            href="https://github.com/ituzov/director"
            target="_blank"
            rel="noreferrer"
            className="hover:underline"
          >
            GitHub
          </a>
        </div>
      </aside>

      <main className="flex items-center justify-center px-4 py-8">
        <div className="grid w-full max-w-md gap-6">
          <div className="grid justify-items-center gap-2 text-center">
            <div className="flex items-center gap-3">
              <Logo />
              <h1 className="text-2xl font-semibold">{title}</h1>
            </div>
            <p className="text-sm text-muted-foreground">{description}</p>
          </div>
          {children}
        </div>
      </main>
    </div>
  );
}

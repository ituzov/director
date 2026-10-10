import { redirect } from "next/navigation";
import { useTranslations } from "next-intl";
import { Suspense } from "react";

import { AuthShell } from "@/components/auth-shell";
import { apiFetch } from "@/lib/api";

import { SetupForm } from "./_components/setup-form";

export default function SetupPage({ searchParams }: PageProps<"/[locale]/setup">) {
  const t = useTranslations("Setup");

  return (
    <AuthShell title={t("title")} description={t("description")}>
      <Suspense>
        <Setup searchParams={searchParams} />
      </Suspense>
    </AuthShell>
  );
}

async function Setup({ searchParams }: Pick<PageProps<"/[locale]/setup">, "searchParams">) {
  // сначала то, что есть только у запроса: при сборке рендер остановится здесь, а не на api
  const { token } = await searchParams;

  const { needed } = await apiFetch<{ needed: boolean }>("/setup");
  if (!needed) redirect("/login");

  return <SetupForm token={typeof token === "string" ? token : undefined} />;
}

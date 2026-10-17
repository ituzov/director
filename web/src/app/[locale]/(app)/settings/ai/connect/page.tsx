import { Sparkles } from "lucide-react";
import { notFound } from "next/navigation";
import { useTranslations } from "next-intl";
import { Suspense } from "react";

import { Page, Panel } from "@/components/page";
import { getCurrentUser } from "@/lib/session";

import { ConnectForm } from "./_components/connect-form";

export default function ConnectPage() {
  const t = useTranslations("Ai.connect");

  return (
    <Page>
      <Panel icon={Sparkles} title={t("title")} description={t("description")}>
        <Suspense>
          <Connect />
        </Suspense>
      </Panel>
    </Page>
  );
}

async function Connect() {
  // как и список, только для владельца: остальным страницы будто нет
  if ((await getCurrentUser()).role !== "owner") notFound();
  return <ConnectForm />;
}

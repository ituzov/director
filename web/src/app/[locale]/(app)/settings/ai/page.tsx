import { Sparkles } from "lucide-react";
import { notFound } from "next/navigation";
import { useTranslations } from "next-intl";
import { getTranslations } from "next-intl/server";
import { Suspense } from "react";

import { Page, Panel } from "@/components/page";
import { Button } from "@/components/ui/button";
import { Link } from "@/i18n/navigation";
import type { AiConnection } from "@/lib/ai";
import { ApiError, apiFetch } from "@/lib/api";
import { getCurrentUser, getToken } from "@/lib/session";

import { ConnectionList, ConnectionListSkeleton } from "./_components/connection-list";

export default function AiPage() {
  const t = useTranslations("Ai");

  return (
    <Page>
      <Panel
        icon={Sparkles}
        title={t("title")}
        description={t("description")}
        actions={
          <Button nativeButton={false} render={<Link href="/settings/ai/connect" />}>
            {t("connectButton")}
          </Button>
        }
      >
        <Suspense fallback={<ConnectionListSkeleton />}>
          <Connections />
        </Suspense>
      </Panel>
    </Page>
  );
}

async function Connections() {
  // оба запроса сразу, а не по очереди
  const [user, connections, t] = await Promise.all([
    getCurrentUser(),
    apiFetch<AiConnection[]>("/ai/connections", { token: await getToken() }).catch((e) => {
      // не владелец: api закрыт, решит проверка роли ниже
      if (e instanceof ApiError && e.status === 403) return null;
      throw e;
    }),
    getTranslations("Ai"),
  ]);
  // раздел только для владельца, и api тоже: участнику страницы будто нет
  if (user.role !== "owner" || connections === null) notFound();
  return <ConnectionList connections={connections} empty={t("empty")} />;
}

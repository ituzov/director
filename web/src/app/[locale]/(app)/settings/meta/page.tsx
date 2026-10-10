import { KeyRound } from "lucide-react";
import { notFound } from "next/navigation";
import { useTranslations } from "next-intl";
import { cache, Suspense } from "react";

import { Page, Panel } from "@/components/page";
import { ApiError, apiFetch } from "@/lib/api";
import type { MetaApp } from "@/lib/meta-app";
import { getCurrentUser, getToken } from "@/lib/session";

import { MetaAppForm, MetaAppFormSkeleton } from "./_components/meta-app-form";
import { MetaStrings } from "./_components/meta-strings";

export default function MetaAppPage() {
  const t = useTranslations("MetaApp");

  return (
    <Page>
      {/* шапка панели статическая и видна сразу, форма приезжает потоком */}
      <Panel icon={KeyRound} title={t("keys")} description={t("description")}>
        <Suspense fallback={<MetaAppFormSkeleton />}>
          <MetaAppKeys />
        </Suspense>
      </Panel>
      <Suspense>
        <MetaAppStrings />
      </Suspense>
    </Page>
  );
}

// обе части страницы просят одно и то же: запрос к api один на рендер
const getMetaApp = cache(async (): Promise<MetaApp | null> => {
  const token = await getToken();
  // оба запроса сразу, а не по очереди: api сам пускает только владельца
  const [user, metaApp] = await Promise.all([
    getCurrentUser(),
    apiFetch<MetaApp | null>("/instagram/app", { token }).catch((e) => {
      // нет сессии или не владелец: решит getCurrentUser и проверка роли ниже
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) return undefined;
      throw e;
    }),
  ]);
  // участнику страницы будто нет
  if (user.role !== "owner" || metaApp === undefined) notFound();
  return metaApp;
});

async function MetaAppKeys() {
  const metaApp = await getMetaApp();
  // новая дата после сохранения пересоздаёт форму: поле секрета снова закрыто
  return <MetaAppForm key={metaApp?.updated_at} metaApp={metaApp} />;
}

async function MetaAppStrings() {
  const metaApp = await getMetaApp();
  // строки появляются после первого сохранения: до него нет маркера
  return metaApp && <MetaStrings metaApp={metaApp} />;
}

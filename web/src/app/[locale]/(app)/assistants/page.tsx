import { Bot, Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import { getTranslations } from "next-intl/server";
import { Suspense } from "react";

import { Page, Panel } from "@/components/page";
import { ViewTabs } from "@/components/view-tabs";
import { Button } from "@/components/ui/button";
import { Link } from "@/i18n/navigation";
import { apiFetch } from "@/lib/api";
import type { Assistant } from "@/lib/assistants";
import { getCurrentAccount } from "@/lib/current-account";
import { getCurrentUser, getToken } from "@/lib/session";

import { AssistantList, AssistantListSkeleton } from "./_components/assistant-list";

type Props = { searchParams: Promise<{ archived?: string }> };

export default function AssistantsPage({ searchParams }: Props) {
  const t = useTranslations("Assistants");

  return (
    // список карточек: на широком экране больше карточек в ряд, а не шире строки
    <Page width="wide">
      <Panel
        icon={Bot}
        title={t("title")}
        description={t("description")}
        actions={
          <Suspense>
            <Create />
          </Suspense>
        }
      >
        <Suspense fallback={<AssistantListSkeleton />}>
          <Assistants searchParams={searchParams} />
        </Suspense>
      </Panel>
    </Page>
  );
}

/** Новый ассистент тратит ключ владельца: кнопка только ему. */
async function Create() {
  const [user, t] = await Promise.all([getCurrentUser(), getTranslations("Assistants")]);
  if (user.role !== "owner") return null;
  return (
    // ссылка в виде кнопки: nativeButton={false}, иначе Base UI ждёт настоящий <button>
    <Button nativeButton={false} render={<Link href="/assistants/new" />}>
      <Plus />
      {t("create")}
    </Button>
  );
}

/** Ассистенты аккаунта из переключателя. Читает cookie и api: только внутри Suspense. */
async function Assistants({ searchParams }: Props) {
  const archived = (await searchParams).archived === "1";
  const [account, user] = await Promise.all([getCurrentAccount(), getCurrentUser()]);
  if (!account) return <NoAccount />;
  const query = new URLSearchParams({ account_id: account.id, archived: String(archived) });
  const [assistants, t] = await Promise.all([
    apiFetch<Assistant[]>(`/assistants?${query}`, { token: await getToken() }),
    getTranslations("Assistants.tabs"),
  ]);
  return (
    <>
      <ViewTabs
        label={t("label")}
        tabs={[
          { key: "active", href: "/assistants", label: t("active"), current: !archived },
          {
            key: "archive",
            href: "/assistants?archived=1",
            label: t("archive"),
            current: archived,
          },
        ]}
      />
      <AssistantList assistants={assistants} archived={archived} canEdit={user.role === "owner"} />
    </>
  );
}

function NoAccount() {
  const t = useTranslations("Assistants");
  return (
    <p className="text-sm text-muted-foreground">
      {t.rich("noAccount", {
        link: (chunks) => (
          <Link href="/accounts" className="text-foreground underline">
            {chunks}
          </Link>
        ),
      })}
    </p>
  );
}

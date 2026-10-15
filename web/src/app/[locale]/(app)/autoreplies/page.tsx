import { MessageSquareReply, Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import { getNow, getTranslations } from "next-intl/server";
import { Suspense } from "react";

import { Page, Panel } from "@/components/page";
import { ViewTabs } from "@/components/view-tabs";
import { Button } from "@/components/ui/button";
import { Link } from "@/i18n/navigation";
import { apiFetch } from "@/lib/api";
import { type Autoreply, type AutoreplyStats, STATS_DAYS } from "@/lib/autoreplies";
import { getCurrentAccount } from "@/lib/current-account";
import { getToken } from "@/lib/session";

import { AutoreplyList, AutoreplyListSkeleton } from "./_components/autoreply-list";

type Props = { searchParams: Promise<{ archived?: string }> };

export default function AutorepliesPage({ searchParams }: Props) {
  const t = useTranslations("Autoreplies");

  return (
    // список карточек: на широком экране больше карточек в ряд, а не шире строки
    <Page width="wide">
      <Panel
        icon={MessageSquareReply}
        title={t("title")}
        description={t("description")}
        actions={
          // ссылка в виде кнопки: nativeButton={false}, иначе Base UI ждёт настоящий <button>
          <Button nativeButton={false} render={<Link href="/autoreplies/new" />}>
            <Plus />
            {t("create")}
          </Button>
        }
      >
        <Suspense fallback={<AutoreplyListSkeleton />}>
          <Autoreplies searchParams={searchParams} />
        </Suspense>
      </Panel>
    </Page>
  );
}

/** Автоответы аккаунта из переключателя. Читает cookie и api: только внутри Suspense. */
async function Autoreplies({ searchParams }: Props) {
  const archived = (await searchParams).archived === "1";
  const account = await getCurrentAccount();
  if (!account) return <NoAccount />;

  const token = await getToken();
  const query = new URLSearchParams({ account_id: account.id, archived: String(archived) });
  // один момент на запрос: «2 ч назад» в браузере совпадёт с серверным
  const [autoreplies, stats, now, t] = await Promise.all([
    apiFetch<Autoreply[]>(`/autoreplies?${query}`, { token }),
    // цифры на карточках не главное: сводка упала, список всё равно показываем
    apiFetch<AutoreplyStats>(
      `/autoreplies/stats?${new URLSearchParams({ account_id: account.id, days: String(STATS_DAYS) })}`,
      { token },
    ).catch(() => null),
    getNow(),
    getTranslations("Autoreplies.tabs"),
  ]);
  return (
    <>
      <ViewTabs
        label={t("label")}
        tabs={[
          { key: "active", href: "/autoreplies", label: t("active"), current: !archived },
          {
            key: "archive",
            href: "/autoreplies?archived=1",
            label: t("archive"),
            current: archived,
          },
        ]}
      />
      <AutoreplyList
        autoreplies={autoreplies}
        archived={archived}
        counts={stats && Object.fromEntries(stats.by_autoreply.map((c) => [c.id, c]))}
        now={now.getTime()}
      />
    </>
  );
}

function NoAccount() {
  const t = useTranslations("Autoreplies");
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

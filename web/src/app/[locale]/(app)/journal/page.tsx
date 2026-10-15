import { ScrollText } from "lucide-react";
import { useTranslations } from "next-intl";
import { getNow, getTranslations } from "next-intl/server";
import { Suspense } from "react";

import { Page, Panel } from "@/components/page";
import { ViewTabs } from "@/components/view-tabs";
import { Link } from "@/i18n/navigation";
import { apiFetch } from "@/lib/api";
import type { Autoreply } from "@/lib/autoreplies";
import { getCurrentAccount } from "@/lib/current-account";
import { type DeliveryPage, type StageCounts, stageQuery, type Tab, tabOf } from "@/lib/deliveries";
import { type ResultCounts, resultOf, resultQuery, type ResultTab } from "@/lib/events";
import { INBOX_PAGE, type InboxPage } from "@/lib/inbox";
import { getToken } from "@/lib/session";

import { DeliveryTable } from "./_components/delivery-table";
import { DeliveryTabs } from "./_components/delivery-tabs";
import { EventsTabs } from "./_components/events-tabs";
import { EventsTable, TableSkeleton } from "./_components/events-table";
import { RefreshButton } from "./_components/refresh-button";
import { loadHistory } from "./history";

type Props = {
  searchParams: Promise<{ view?: string; tab?: string | string[]; result?: string | string[] }>;
};

export default function InboxPageRoute({ searchParams }: Props) {
  const t = useTranslations("Inbox");

  return (
    // широкая, хоть это и список: владелец решил, что текст событий важнее узкой колонки
    <Page width="wide">
      <Panel
        icon={ScrollText}
        title={t("title")}
        description={t("description")}
        actions={<RefreshButton />}
      >
        <Suspense fallback={<TableSkeleton />}>
          <Feed searchParams={searchParams} />
        </Suspense>
      </Panel>
    </Page>
  );
}

/** Выбранный вид страницы. Читает cookie и api: только внутри Suspense. */
async function Feed({ searchParams }: Props) {
  const params = await searchParams;
  // по умолчанию выдачи: ради них страницу и открывают
  const all = params.view === "all";
  const account = await getCurrentAccount();
  if (!account) return <NoAccount />;

  const [token, now, t] = await Promise.all([getToken(), getNow(), getTranslations("Inbox.view")]);
  return (
    <>
      <ViewTabs
        label={t("label")}
        tabs={[
          { key: "deliveries", href: "/journal", label: t("deliveries"), current: !all },
          { key: "all", href: "/journal?view=all", label: t("all"), current: all },
        ]}
      />
      {all ? (
        <Events
          accountId={account.id}
          tab={resultOf(params.result)}
          token={token}
          now={now.getTime()}
        />
      ) : (
        <Deliveries
          accountId={account.id}
          tab={tabOf(params.tab)}
          token={token}
          now={now.getTime()}
        />
      )}
    </>
  );
}

type ViewProps = { accountId: string; token: string | undefined; now: number };

/** Выдачи на вкладке этапа со счётчиками вкладок. */
async function Deliveries({ accountId, tab, token, now }: ViewProps & { tab: Tab }) {
  const query = new URLSearchParams([
    ["account_id", accountId],
    ["limit", String(INBOX_PAGE)],
    ...stageQuery(tab),
  ]);
  const [page, { counts }] = await Promise.all([
    apiFetch<DeliveryPage>(`/autoreplies/deliveries?${query}`, { token }),
    apiFetch<{ counts: StageCounts }>(
      `/autoreplies/deliveries/counts?${new URLSearchParams({ account_id: accountId })}`,
      { token },
    ),
  ]);
  // id комментов видны только из ответа: историю спрашиваем вторым заходом
  const history = await loadHistory(
    accountId,
    page.items.map((d) => d.comment_id),
    token,
  );
  return (
    <>
      <DeliveryTabs tab={tab} counts={counts} />
      {/* «Обновить» и смена вкладки дают новый ключ: список собирается с первой страницы */}
      <DeliveryTable
        key={`${accountId}:${tab}:${now}`}
        accountId={accountId}
        tab={tab}
        initial={page}
        history={history}
        now={now}
      />
    </>
  );
}

/** Все события от Meta на вкладке итога: что пришло и чем кончился разбор, без истории
 * выдач. С названиями автоответов и счётчиками. */
async function Events({ accountId, tab, token, now }: ViewProps & { tab: ResultTab }) {
  // названия ищем здесь, а не в api: instagram про автоответы не знает.
  // Архивные тоже: в истории есть события, которые они взяли
  const autoreplies = (archived: boolean) =>
    apiFetch<Autoreply[]>(
      `/autoreplies?${new URLSearchParams({ account_id: accountId, archived: String(archived) })}`,
      { token },
    );
  const query = new URLSearchParams([["limit", String(INBOX_PAGE)], ...resultQuery(tab)]);
  const [page, { counts }, active, archived] = await Promise.all([
    apiFetch<InboxPage>(`/instagram/accounts/${accountId}/inbox?${query}`, { token }),
    apiFetch<{ counts: ResultCounts }>(`/instagram/accounts/${accountId}/inbox/counts`, {
      token,
    }),
    autoreplies(false),
    autoreplies(true),
  ]);
  const names = Object.fromEntries([...active, ...archived].map((a) => [a.id, a.name]));
  return (
    <>
      <EventsTabs tab={tab} counts={counts} />
      {/* «Обновить» и смена вкладки дают новый ключ: список собирается с первой страницы */}
      <EventsTable
        key={`${accountId}:${tab}:${now}`}
        accountId={accountId}
        tab={tab}
        initial={page}
        names={names}
        now={now}
      />
    </>
  );
}

function NoAccount() {
  const t = useTranslations("Inbox");
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

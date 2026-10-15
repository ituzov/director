import { Inbox } from "lucide-react";
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
import { INBOX_PAGE, type InboxPage } from "@/lib/inbox";
import { getToken } from "@/lib/session";

import { DeliveryTable } from "./_components/delivery-table";
import { DeliveryTabs } from "./_components/delivery-tabs";
import { InboxList, InboxListSkeleton } from "./_components/inbox-list";
import { RefreshButton } from "./_components/refresh-button";
import { loadHistory } from "./history";

type Props = { searchParams: Promise<{ view?: string; tab?: string | string[] }> };

export default function InboxPageRoute({ searchParams }: Props) {
  const t = useTranslations("Inbox");

  return (
    // список: узкая колонка
    <Page>
      <Panel
        icon={Inbox}
        title={t("title")}
        description={t("description")}
        actions={<RefreshButton />}
      >
        <Suspense fallback={<InboxListSkeleton />}>
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
          { key: "deliveries", href: "/inbox", label: t("deliveries"), current: !all },
          { key: "all", href: "/inbox?view=all", label: t("all"), current: all },
        ]}
      />
      {all ? (
        <Events accountId={account.id} token={token} now={now.getTime()} />
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

/** Все события от Meta лентой, с названиями автоответов. */
async function Events({ accountId, token, now }: ViewProps) {
  // названия ищем здесь, а не в api: instagram про автоответы не знает.
  // Архивные тоже: в истории есть события, которые они взяли
  const autoreplies = (archived: boolean) =>
    apiFetch<Autoreply[]>(
      `/autoreplies?${new URLSearchParams({ account_id: accountId, archived: String(archived) })}`,
      { token },
    );
  const [page, active, archived] = await Promise.all([
    apiFetch<InboxPage>(
      `/instagram/accounts/${accountId}/inbox?${new URLSearchParams({ limit: String(INBOX_PAGE) })}`,
      { token },
    ),
    autoreplies(false),
    autoreplies(true),
  ]);
  const names = Object.fromEntries([...active, ...archived].map((a) => [a.id, a.name]));
  const history = await loadHistory(
    accountId,
    page.items.map((i) => i.comment_id),
    token,
  );
  return (
    <InboxList
      key={`${accountId}:${now}`}
      accountId={accountId}
      initial={page}
      history={history}
      names={names}
      now={now}
    />
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

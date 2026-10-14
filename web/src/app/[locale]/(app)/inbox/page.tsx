import { Inbox } from "lucide-react";
import { useTranslations } from "next-intl";
import { getNow } from "next-intl/server";
import { Suspense } from "react";

import { Page, Panel } from "@/components/page";
import { Link } from "@/i18n/navigation";
import { apiFetch } from "@/lib/api";
import type { Autoreply } from "@/lib/autoreplies";
import { getCurrentAccount } from "@/lib/current-account";
import { INBOX_PAGE, type InboxPage } from "@/lib/inbox";
import { getToken } from "@/lib/session";

import { InboxList, InboxListSkeleton } from "./_components/inbox-list";
import { RefreshButton } from "./_components/refresh-button";

export default function InboxPageRoute() {
  const t = useTranslations("Inbox");

  return (
    // лента это список: узкая колонка, время рядом с итогом
    <Page>
      <Panel
        icon={Inbox}
        title={t("title")}
        description={t("description")}
        actions={<RefreshButton />}
      >
        <Suspense fallback={<InboxListSkeleton />}>
          <Feed />
        </Suspense>
      </Panel>
    </Page>
  );
}

/** Первая страница ленты и названия автоответов. Читает cookie и api: только внутри Suspense. */
async function Feed() {
  const account = await getCurrentAccount();
  if (!account) return <NoAccount />;

  const token = await getToken();
  // названия ищем здесь, а не в api: instagram про автоответы не знает.
  // Архивные тоже: в истории есть события, которые они взяли
  const autoreplies = (archived: boolean) =>
    apiFetch<Autoreply[]>(
      `/autoreplies?${new URLSearchParams({ account_id: account.id, archived: String(archived) })}`,
      { token },
    );
  const [page, active, archived, now] = await Promise.all([
    apiFetch<InboxPage>(
      `/instagram/accounts/${account.id}/inbox?${new URLSearchParams({ limit: String(INBOX_PAGE) })}`,
      { token },
    ),
    autoreplies(false),
    autoreplies(true),
    getNow(),
  ]);
  const names = Object.fromEntries([...active, ...archived].map((a) => [a.id, a.name]));
  return (
    // «Обновить» даёт новый now: список собирается заново с первой страницы
    <InboxList
      key={`${account.id}:${now.getTime()}`}
      accountId={account.id}
      initial={page}
      names={names}
      now={now.getTime()}
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

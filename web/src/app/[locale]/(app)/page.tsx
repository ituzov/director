import { ChartNoAxesColumn, CircleAlert, CircleCheck, Circle, ListChecks } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { Suspense } from "react";

import { Page, Panel } from "@/components/page";
import { Skeleton } from "@/components/ui/skeleton";
import { Link } from "@/i18n/navigation";
import type { Account } from "@/lib/accounts";
import { ApiError, apiFetch } from "@/lib/api";
import { type Autoreply, type AutoreplyStats, STATS_DAYS as DAYS } from "@/lib/autoreplies";
import { getCurrentAccount, getSwitchableAccounts } from "@/lib/current-account";
import type { MetaApp } from "@/lib/meta-app";
import { getCurrentUser, getToken } from "@/lib/session";

export default function OverviewPage() {
  return (
    <Page width="wide">
      {/* без заглушки: пока не ясно, всё ли настроено, пустое место честнее скелета */}
      <Suspense>
        <Setup />
      </Suspense>
      <Suspense fallback={<StatsSkeleton />}>
        <Stats />
      </Suspense>
    </Page>
  );
}

/** Что ещё не настроено. Когда всё сделано, панели нет. */
async function Setup() {
  const token = await getToken();
  const [user, accounts, account] = await Promise.all([
    getCurrentUser(),
    getSwitchableAccounts(),
    getCurrentAccount(),
  ]);
  const [metaApp, autoreplyDone] = await Promise.all([
    // приложение Meta видит только владелец: участнику этот шаг не показываем
    user.role === "owner"
      ? apiFetch<MetaApp | null>("/instagram/app", { token }).catch((e) => {
          if (e instanceof ApiError && e.status === 403) return null;
          throw e;
        })
      : undefined,
    account ? hasAutoreply(account.id, token) : false,
  ]);

  const all: Step[] = [
    { key: "metaApp", href: "/settings/meta", done: Boolean(metaApp?.webhook_verified_at) },
    { key: "account", href: "/accounts", done: accounts.some((a) => a.status === "active") },
    { key: "autoreply", href: "/autoreplies/new", done: autoreplyDone },
  ];
  const steps = all.filter((s) => s.key !== "metaApp" || metaApp !== undefined);
  if (steps.every((s) => s.done)) return null;
  return <SetupPanel steps={steps} />;
}

/** Создавал ли автоответ: архивный тоже считается, чек-лист про пройденную настройку. */
async function hasAutoreply(accountId: string, token: string | undefined) {
  const list = (archived: boolean) =>
    apiFetch<Autoreply[]>(
      `/autoreplies?${new URLSearchParams({ account_id: accountId, archived: String(archived) })}`,
      { token },
    );
  // архив спрашиваем, только если активных нет: обычно хватает одного запроса
  return (await list(false)).length > 0 || (await list(true)).length > 0;
}

type Step = { key: "metaApp" | "account" | "autoreply"; href: string; done: boolean };

function SetupPanel({ steps }: { steps: Step[] }) {
  const t = useTranslations("Overview.setup");
  // следующий шаг ссылкой, остальные текстом: идти по порядку, а не прыгать
  const nextKey = steps.find((s) => !s.done)?.key;

  return (
    <Panel icon={ListChecks} title={t("title")} description={t("description")}>
      <ol className="grid gap-3">
        {steps.map(({ key, href, done }) => (
          <li key={key} className="flex items-center gap-3 text-sm">
            {done ? (
              <CircleCheck className="size-5 shrink-0 text-primary" aria-label={t("done")} />
            ) : (
              <Circle className="size-5 shrink-0 text-muted-foreground" />
            )}
            {key === nextKey ? (
              <Link href={href} className="font-medium underline underline-offset-4">
                {t(key)}
              </Link>
            ) : (
              <span className={done ? "text-muted-foreground line-through" : undefined}>
                {t(key)}
              </span>
            )}
          </li>
        ))}
      </ol>
    </Panel>
  );
}

/** Воронка выбранного аккаунта. Без аккаунта считать нечего: это скажет Setup. */
async function Stats() {
  const account = await getCurrentAccount();
  if (!account) return null;
  const query = new URLSearchParams({ account_id: account.id, days: String(DAYS) });
  const stats = await apiFetch<AutoreplyStats>(`/autoreplies/stats?${query}`, {
    token: await getToken(),
  });
  return <StatsPanel account={account} stats={stats} />;
}

function StatsPanel({ account, stats }: { account: Account; stats: AutoreplyStats }) {
  const t = useTranslations("Overview.stats");
  const format = useFormatter();
  const steps = [
    { key: "triggered", value: stats.triggered, prev: null },
    { key: "sent", value: stats.sent, prev: stats.triggered },
    { key: "clicked", value: stats.clicked, prev: stats.sent },
    { key: "delivered", value: stats.delivered, prev: stats.clicked },
  ] as const;

  return (
    <Panel
      icon={ChartNoAxesColumn}
      title={t("title", { days: DAYS })}
      description={t("description", { username: account.username })}
    >
      <Alerts account={account} undelivered={stats.undelivered} />

      <dl className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {steps.map(({ key, value, prev }) => (
          <div key={key} className="grid gap-1 rounded-lg border p-4">
            <dt className="text-sm text-muted-foreground">{t(key)}</dt>
            <dd className="text-2xl font-semibold tabular-nums">{format.number(value)}</dd>
            {/* доля от прошлого шага: где теряются люди */}
            {prev !== null && (
              <dd className="text-xs text-muted-foreground">
                {prev
                  ? t("ofPrevious", {
                      value: format.number(value / prev, { style: "percent" }),
                    })
                  : " "}
              </dd>
            )}
          </div>
        ))}
      </dl>

      {stats.triggered === 0 ? (
        <p className="text-sm text-muted-foreground">{t("empty", { days: DAYS })}</p>
      ) : (
        <div className="grid gap-2">
          <h3 className="text-sm font-medium">{t("top")}</h3>
          <ul className="divide-y rounded-lg border">
            {stats.top.map((a) => (
              <li key={a.id}>
                <Link
                  href={`/autoreplies/${a.id}`}
                  className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 px-4 py-3 text-sm hover:bg-muted/50"
                >
                  <span className="font-medium">{a.name}</span>
                  <span className="text-muted-foreground tabular-nums">
                    {t("topRow", { triggered: a.triggered, delivered: a.delivered })}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Panel>
  );
}

/** Что мешает автоответам работать прямо сейчас. */
function Alerts({ account, undelivered }: { account: Account; undelivered: number }) {
  const t = useTranslations("Overview.alerts");
  const alerts = [
    account.status === "token_expired" &&
      t.rich("tokenExpired", {
        username: account.username,
        link: (chunks) => (
          <Link href="/accounts" className="underline underline-offset-4">
            {chunks}
          </Link>
        ),
      }),
    undelivered > 0 && t("undelivered", { count: undelivered, days: DAYS }),
  ].filter(Boolean);
  if (alerts.length === 0) return null;

  return (
    <ul className="grid gap-2">
      {alerts.map((alert, i) => (
        <li
          key={i}
          role="alert"
          className="flex gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
        >
          <CircleAlert className="mt-0.5 size-4 shrink-0" />
          <span>{alert}</span>
        </li>
      ))}
    </ul>
  );
}

function StatsSkeleton() {
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      {Array.from({ length: 4 }, (_, i) => (
        <Skeleton key={i} className="h-24 rounded-lg" />
      ))}
    </div>
  );
}

import { AtSign } from "lucide-react";
import { useTranslations } from "next-intl";
import { getTranslations } from "next-intl/server";
import { Suspense } from "react";

import { Page, Panel } from "@/components/page";
import type { Account, ConnectResult } from "@/lib/accounts";
import { apiFetch } from "@/lib/api";
import { getCurrentUser, getToken } from "@/lib/session";

import { AccountList, AccountListSkeleton } from "./_components/account-list";
import { ConnectButton } from "./_components/connect-button";

type Props = { searchParams: Promise<{ result?: string; username?: string }> };

export default function AccountsPage({ searchParams }: Props) {
  const t = useTranslations("Accounts");

  return (
    <Page>
      <Panel
        icon={AtSign}
        title={t("title")}
        description={t("description")}
        actions={
          <Suspense fallback={<ConnectButton disabled />}>
            <Connect />
          </Suspense>
        }
      >
        <Suspense>
          <Result searchParams={searchParams} />
        </Suspense>
        <Suspense fallback={<AccountListSkeleton />}>
          <Accounts />
        </Suspense>
      </Panel>
    </Page>
  );
}

async function Connect() {
  const user = await getCurrentUser();
  // подключать может владелец или участник с правом, остальным кнопка не нужна
  return <ConnectButton disabled={user.role !== "owner" && !user.can_connect_accounts} />;
}

async function Accounts() {
  const accounts = await apiFetch<Account[]>("/instagram/accounts", { token: await getToken() });
  return <AccountList accounts={accounts} />;
}

const RESULTS: ConnectResult[] = [
  "connected",
  "denied",
  "expired",
  "failed",
  "forbidden",
  "MetaAppRequired",
  "PublicUrlRequired",
];

/** Чем закончился вход через Instagram: результат приходит в адресе после возврата. */
async function Result({ searchParams }: Props) {
  const { result, username } = await searchParams;
  const t = await getTranslations("Accounts");
  // в адресе может быть что угодно: показываем только известные исходы
  const known = RESULTS.find((r) => r === result);
  if (!known) return null;
  const ok = known === "connected";
  return (
    <p
      role={ok ? "status" : "alert"}
      className={ok ? "text-sm text-brand" : "text-sm text-destructive"}
    >
      {t(`result.${known}`, { username: username ?? "" })}
    </p>
  );
}

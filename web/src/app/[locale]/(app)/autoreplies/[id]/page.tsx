import { notFound } from "next/navigation";
import { Suspense } from "react";

import { ApiError, apiFetch } from "@/lib/api";
import type { Autoreply } from "@/lib/autoreplies";
import { getSwitchableAccounts } from "@/lib/current-account";
import { getToken } from "@/lib/session";

import { AutoreplyForm } from "../_components/autoreply-form";

type Props = { params: Promise<{ id: string }> };

export default function AutoreplyPage({ params }: Props) {
  return (
    <Suspense>
      <Edit params={params} />
    </Suspense>
  );
}

/** Ходит в api с сессией: только внутри Suspense. */
async function Edit({ params }: Props) {
  const { id } = await params;
  let autoreply: Autoreply;
  try {
    autoreply = await apiFetch<Autoreply>(`/autoreplies/${id}`, { token: await getToken() });
  } catch (e) {
    // не uuid api отвергает 422, чужой или удалённый 404: для человека одно и то же
    if (e instanceof ApiError && (e.status === 404 || e.status === 422)) notFound();
    throw e;
  }
  // ник для превью: аккаунт автоответа, а не выбранный в меню
  const account = (await getSwitchableAccounts()).find((a) => a.id === autoreply.account_id);
  return (
    <AutoreplyForm
      autoreply={autoreply}
      accountId={autoreply.account_id}
      username={account?.username ?? null}
    />
  );
}

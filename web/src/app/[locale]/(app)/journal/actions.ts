"use server";

import { apiFetch } from "@/lib/api";
import { type DeliveryPage, stageQuery, tabOf } from "@/lib/deliveries";
import { resultOf, resultQuery } from "@/lib/events";
import { type History, INBOX_PAGE, type InboxPage } from "@/lib/inbox";
import { getToken } from "@/lib/session";

import { loadHistory } from "./history";

/** Следующая страница ленты на вкладке итога: события старше закладки before.
 * Вкладку присылает браузер: незнакомая значит «все». */
export async function loadInbox(
  accountId: string,
  before: string,
  tab: string,
): Promise<{ page: InboxPage }> {
  const token = await getToken();
  const query = new URLSearchParams([
    ["before", before],
    ["limit", String(INBOX_PAGE)],
    ...resultQuery(resultOf(tab)),
  ]);
  const page = await apiFetch<InboxPage>(`/instagram/accounts/${accountId}/inbox?${query}`, {
    token,
  });
  return { page };
}

/** Следующая страница выдач на вкладке: старше закладки before, с историей. Вкладку
 * присылает браузер: незнакомая значит «все». */
export async function loadDeliveries(
  accountId: string,
  before: string,
  tab: string,
): Promise<{ page: DeliveryPage; history: History }> {
  const token = await getToken();
  const query = new URLSearchParams([
    ["account_id", accountId],
    ["before", before],
    ["limit", String(INBOX_PAGE)],
    ...stageQuery(tabOf(tab)),
  ]);
  const page = await apiFetch<DeliveryPage>(`/autoreplies/deliveries?${query}`, { token });
  const history = await loadHistory(
    accountId,
    page.items.map((d) => d.comment_id),
    token,
  );
  return { page, history };
}

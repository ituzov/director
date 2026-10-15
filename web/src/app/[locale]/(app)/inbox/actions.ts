"use server";

import { apiFetch } from "@/lib/api";
import { type History, INBOX_PAGE, type InboxPage } from "@/lib/inbox";
import { getToken } from "@/lib/session";

import { loadHistory } from "./history";

/** Следующая страница ленты: события старше закладки before, с историей их комментов. */
export async function loadInbox(
  accountId: string,
  before: string,
): Promise<{ page: InboxPage; history: History }> {
  const token = await getToken();
  const query = new URLSearchParams({ before, limit: String(INBOX_PAGE) });
  const page = await apiFetch<InboxPage>(`/instagram/accounts/${accountId}/inbox?${query}`, {
    token,
  });
  return { page, history: await loadHistory(accountId, page.items, token) };
}

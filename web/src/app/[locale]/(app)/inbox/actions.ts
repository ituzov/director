"use server";

import { apiFetch } from "@/lib/api";
import { INBOX_PAGE, type InboxPage } from "@/lib/inbox";
import { getToken } from "@/lib/session";

/** Следующая страница ленты: события старше закладки before. */
export async function loadInbox(accountId: string, before: string): Promise<InboxPage> {
  const query = new URLSearchParams({ before, limit: String(INBOX_PAGE) });
  return apiFetch<InboxPage>(`/instagram/accounts/${accountId}/inbox?${query}`, {
    token: await getToken(),
  });
}

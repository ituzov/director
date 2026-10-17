import "server-only";

import type { Media } from "@/lib/accounts";
import { ApiError, apiFetch } from "@/lib/api";
import { getToken } from "@/lib/session";

// Посты аккаунта для выбора в форме: автоответы и ассистенты. Чей пост уже занят,
// решает модуль по своему списку, здесь только лента Meta

/** Кто держит пост: форма покажет плашку «Автоответ «Гайд», выключен». */
export type TakenBy = { id: string; name: string; enabled: boolean };

/** Владелец постов из списка модуля: автоответ или ассистент. */
type PostOwner = TakenBy & { media_ids: string[] };

// аккаунт отключён или токен истёк: повтор не поможет. Meta не ответила: поможет
type Failed = { failed: "AccountUnavailable" | "MetaUnavailable" };

export type MediaPage =
  { items: Media[]; next: string | null; taken: Record<string, TakenBy> } | Failed;

// missing: пост удалили или убрали в архив, а владелец на нём ещё висит
export type SelectedMedia = { items: Media[]; missing: string[] } | Failed;

/** Страница постов из Meta и кто из них занят. Сам правимый (ownId) пост не занимает. */
export async function mediaPage(
  accountId: string | null,
  ownId: string | null,
  after: string | null,
  owners: (token: string | undefined) => Promise<PostOwner[]>,
): Promise<MediaPage> {
  if (!accountId) return { failed: "AccountUnavailable" };
  const token = await getToken();
  // 8 это два ряда в окне выбора, дальше «Показать ещё»
  const query = new URLSearchParams({ limit: "8", ...(after && { after }) });
  try {
    const [page, held] = await Promise.all([
      apiFetch<{ items: Media[]; next: string | null }>(
        `/instagram/accounts/${accountId}/media?${query}`,
        { token },
      ),
      owners(token),
    ]);
    const taken: Record<string, TakenBy> = {};
    for (const { id, name, enabled, media_ids } of held) {
      if (id === ownId) continue;
      for (const mediaId of media_ids) taken[mediaId] = { id, name, enabled };
    }
    return { ...page, taken };
  } catch (e) {
    const failed = failure(e);
    if (failed) return failed;
    throw e;
  }
}

/** Миниатюры уже выбранных постов, для ряда в форме. */
export async function selectedMedia(accountId: string, ids: string[]): Promise<SelectedMedia> {
  const query = new URLSearchParams(ids.map((id) => ["ids", id]));
  try {
    return await apiFetch<{ items: Media[]; missing: string[] }>(
      `/instagram/accounts/${accountId}/media/selected?${query}`,
      { token: await getToken() },
    );
  } catch (e) {
    const failed = failure(e);
    if (failed) return failed;
    throw e;
  }
}

function failure(e: unknown): Failed | null {
  if (
    e instanceof ApiError &&
    (e.detail === "AccountUnavailable" || e.detail === "MetaUnavailable")
  ) {
    return { failed: e.detail };
  }
  return null;
}

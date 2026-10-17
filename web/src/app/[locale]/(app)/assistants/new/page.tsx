import { notFound } from "next/navigation";
import { Suspense } from "react";

import type { AiConnection } from "@/lib/ai";
import { ApiError, apiFetch } from "@/lib/api";
import type { Assistant } from "@/lib/assistants";
import { getCurrentAccount } from "@/lib/current-account";
import { getCurrentUser, getToken } from "@/lib/session";

import { AssistantForm } from "../_components/assistant-form";

/** Новый ассистент выбранного в меню аккаунта. Аккаунт уходит в форму скрытым
 * полем: сохранится туда, для какого открыли, что бы ни выбрали в другой вкладке. */
export default function NewAssistantPage() {
  return (
    <Suspense>
      <New />
    </Suspense>
  );
}

/** Читает cookie и api: только внутри Suspense. */
async function New() {
  const [user, account] = await Promise.all([getCurrentUser(), getCurrentAccount()]);
  // создать может только владелец: ассистент тратит его ключ
  if (user.role !== "owner") notFound();
  const token = await getToken();
  const [connections, assistants] = await Promise.all([
    apiFetch<AiConnection[]>("/ai/connections", { token }),
    account
      ? apiFetch<Assistant[]>(`/assistants?${new URLSearchParams({ account_id: account.id })}`, {
          token,
        }).catch((e) => {
          if (e instanceof ApiError) return [];
          throw e;
        })
      : Promise.resolve([]),
  ]);
  // «по умолчанию как у последнего»: подключение и модель свежего ассистента
  const last = [...assistants].sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0];
  return (
    <AssistantForm
      assistant={null}
      accountId={account?.id ?? null}
      connections={connections}
      defaults={{ connectionId: last?.connection_id ?? null, model: last?.model ?? null }}
      canEdit
    />
  );
}

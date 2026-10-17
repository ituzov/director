import { notFound } from "next/navigation";
import { Suspense } from "react";

import type { AiConnection } from "@/lib/ai";
import { ApiError, apiFetch } from "@/lib/api";
import type { Assistant } from "@/lib/assistants";
import { getCurrentUser, getToken } from "@/lib/session";

import { AssistantForm } from "../_components/assistant-form";

type Props = { params: Promise<{ id: string }> };

export default function AssistantPage({ params }: Props) {
  return (
    <Suspense>
      <Edit params={params} />
    </Suspense>
  );
}

/** Ходит в api с сессией: только внутри Suspense. */
async function Edit({ params }: Props) {
  const { id } = await params;
  const token = await getToken();
  const [user, assistant] = await Promise.all([
    getCurrentUser(),
    apiFetch<Assistant>(`/assistants/${id}`, { token }).catch((e) => {
      // не uuid api отвергает 422, чужой или удалённый 404: для человека одно и то же
      if (e instanceof ApiError && (e.status === 404 || e.status === 422)) notFound();
      throw e;
    }),
  ]);
  const canEdit = user.role === "owner";
  // подключения видит только владелец: участнику модель текстом
  const connections = canEdit ? await apiFetch<AiConnection[]>("/ai/connections", { token }) : null;
  return (
    <AssistantForm
      assistant={assistant}
      accountId={assistant.account_id}
      connections={connections}
      defaults={{ connectionId: null, model: null }}
      canEdit={canEdit}
    />
  );
}

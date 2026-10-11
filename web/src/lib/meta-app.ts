/** Приложение Meta установки, как его отдаёт GET /instagram/app. */
export type MetaApp = {
  app_id: string;
  verify_token: string;
  updated_at: string;
  // Meta подтвердила адрес вебхука; null, пока владелец не нажал «Подтвердить» в кабинете
  webhook_verified_at: string | null;
  // строки для кабинета Meta, null пока у api не задан PUBLIC_URL
  webhook_url: string | null;
  redirect_uri: string | null;
  privacy_url: string | null;
};

// имена совпадают с ключами MetaApp.webhook.errors в messages
export type WebhookCheckError =
  "no_app" | "no_public_url" | "timeout" | "tls" | "unreachable" | "bad_status" | "bad_body";

/** Ответ самопроверки POST /instagram/app/webhook-check. */
export type WebhookCheck = { ok: boolean; error: WebhookCheckError | null };

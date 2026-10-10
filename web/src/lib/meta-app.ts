/** Приложение Meta установки, как его отдаёт GET /instagram/app. */
export type MetaApp = {
  app_id: string;
  verify_token: string;
  updated_at: string;
  // строки для кабинета Meta, null пока у api не задан PUBLIC_URL
  webhook_url: string | null;
  redirect_uri: string | null;
  privacy_url: string | null;
};

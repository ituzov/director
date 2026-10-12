/** Подключённый аккаунт Instagram, как его отдаёт GET /instagram/accounts. Токена нет. */
export type Account = {
  id: string;
  ig_user_id: string;
  username: string;
  status: "active" | "token_expired" | "disconnected";
  connected_at: string;
};

/** Пост аккаунта, как его отдают GET /instagram/accounts/{id}/media и /media/selected. */
export type Media = {
  id: string;
  caption: string | null;
  // FEED или REELS
  type: string | null;
  // ссылка подписана Meta и живёт несколько дней: не храним, только показываем
  thumbnail: string | null;
  permalink: string | null;
  timestamp: string | null;
};

// чем закончилось подключение: ключи AccountsPage.result в messages
export type ConnectResult =
  | "connected"
  | "denied"
  | "expired"
  | "failed"
  | "forbidden"
  | "MetaAppRequired"
  | "PublicUrlRequired";

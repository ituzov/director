/** Подключённый аккаунт Instagram, как его отдаёт GET /instagram/accounts. Токена нет. */
export type Account = {
  id: string;
  ig_user_id: string;
  username: string;
  status: "active" | "token_expired" | "disconnected";
  connected_at: string;
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

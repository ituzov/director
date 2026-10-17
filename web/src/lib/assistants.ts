/** Ассистенты аккаунта, как их отдают ручки /assistants. */

export type AssistantMode = "direct" | "comment" | "combo";

export type Assistant = {
  id: string;
  account_id: string;
  name: string;
  // all: общий, все посты без своего ассистента; posts: только media_ids
  scope: "all" | "posts";
  media_ids: string[];
  mode: AssistantMode;
  instruction: string;
  knowledge: string;
  daily_limit: number;
  enabled: boolean;
  archived_at: string | null;
  // null: подключение удалили, ассистент молчит, пока не выберут другое
  connection_id: string | null;
  model: string | null;
  // провайдер сказал, что модели нет: выбрать другую
  model_missing: boolean;
  // итоги прочитанных за сутки UTC
  today: { answered: number; unsure: number; not_mine: number };
  updated_at: string;
};

/** Место занято: общий у аккаунта один, пост у одного частного. */
export type AssistantConflict = {
  kind: "general" | "post";
  // id поста или null для общего
  value: string | null;
  assistant: { id: string; name: string; enabled: boolean };
};

/** Как ответил бы ассистент в песочнице. error: нейросеть не ответила, код ai. */
export type TryResult = {
  decision: "answer" | "unsure" | "not_mine" | null;
  comment: string | null;
  direct: string | null;
  source: string | null;
  error: string | null;
};

// те же пределы, что у api (assistant/schemas.py): ошибка видна сразу
export const LIMITS = {
  name: 100,
  instruction: 5_000,
  knowledge: 50_000,
  dailyLimit: 10_000,
  comment: 2_200,
} as const;

/** Входящее для ленты, как его отдаёт api (GET /instagram/accounts/{id}/inbox). */
export type InboxItem = {
  id: string;
  received_at: string;
  kind: "comment" | "postback" | "message";
  person_id: string | null;
  // в нажатиях и сообщениях Meta ника не присылает: api берёт его из комментов
  username: string | null;
  // текст коммента или сообщения, подпись нажатой кнопки
  text: string | null;
  // вид вложения сообщения без текста: ig_reel, image, share
  attachment: string | null;
  media_id: string | null;
  // null: ещё не разобрано
  outcome: "done" | "skipped" | "failed" | null;
  reason: string | null;
  // кто взял событие и что именно у него (для автоответов id автоответа)
  handled_by: string | null;
  handled_ref: string | null;
};

export type InboxPage = { items: InboxItem[]; next: string | null };

// одна страница ленты: около экрана с запасом, дальше «Показать ещё»
export const INBOX_PAGE = 50;

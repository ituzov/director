/** Автоответ, как его отдаёт api (GET /autoreplies). */
export type Autoreply = {
  id: string;
  account_id: string;
  name: string;
  scope: "all" | "posts";
  media_ids: string[];
  // как ввёл владелец, в порядке ввода
  keywords: string[];
  intro_text: string;
  button_text: string;
  reply_text: string;
  follow_gate: boolean;
  not_following_text: string | null;
  comment_replies: string[];
  comment_reply_mode: "random" | "sequence";
  enabled: boolean;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
};

/** Слово или пост уже заняты другим автоответом: detail AutoreplyConflict в api. */
export type AutoreplyConflict = {
  kind: "keyword" | "post";
  // слово как ввёл владелец или id поста
  value: string;
  autoreply: { id: string; name: string; enabled: boolean };
};

/** Слово в виде для сравнения, как в api: нижний регистр, ё как е, только буквы
 * и цифры. По нему форма отсекает дубли «Гайд» и «гайд!» до отправки. */
export function normalizeKeyword(word: string): string {
  return (
    word
      .toLowerCase()
      .replaceAll("ё", "е")
      .match(/[\p{L}\p{N}_]+/gu) ?? []
  ).join(" ");
}

// лимиты Meta, те же, что проверяет api
export const LIMITS = {
  // сообщение с кнопкой
  buttonMessage: 640,
  button: 20,
  // обычное сообщение: в байтах UTF-8
  messageBytes: 1000,
  commentReply: 2200,
  commentReplies: 10,
  keywords: 50,
  name: 100,
} as const;

// период сводки на обзоре и карточках; переключатель 7 / 30 дней позже, api его уже умеет
export const STATS_DAYS = 7;

/** Сводка аккаунта: GET /autoreplies/stats. */
export type AutoreplyStats = {
  // сработало, ушёл директ с кнопкой, нажали кнопку, получили материал
  triggered: number;
  sent: number;
  clicked: number;
  delivered: number;
  // отправки, которые так и не ушли: Meta отказала или окно ответа закрылось
  undelivered: number;
  // до пяти чаще всех срабатывавших: для обзора
  top: AutoreplyCounts[];
  // все срабатывавшие за период: для карточек. Кого нет, тот не срабатывал
  by_autoreply: AutoreplyCounts[];
};

/** Цифры одного автоответа за период. */
export type AutoreplyCounts = {
  id: string;
  name: string;
  triggered: number;
  delivered: number;
  // последнее срабатывание
  last_at: string;
};

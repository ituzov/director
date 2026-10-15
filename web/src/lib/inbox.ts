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

/** Шаг выдачи, как его отдаёт api (GET /autoreplies/history). */
export type Step = {
  step:
    | "matched"
    | "repeat_comment"
    | "dm_sent"
    | "commented"
    | "clicked"
    | "repeat_click"
    | "follow_asked"
    | "delivered"
    | "dm_failed"
    | "comment_failed"
    | "material_failed"
    | "send_failed";
  at: string;
  autoreply_id: string | null;
  // слово, на которое сработал автоответ
  keyword: string | null;
  // неудачная отправка: failed или expired, и код ошибки Meta или причина api
  outcome: string | null;
  reason: string | null;
  // у материала: unknown, если Meta не дала проверить подписку
  follow: string | null;
};

// шаги по id коммента; коммента без шагов в ответе нет
export type History = Record<string, Step[]>;

export type Summary =
  | "sending"
  | "waiting_click"
  | "clicked"
  | "follow_asked"
  | "delivered"
  | "repeat_comment"
  | "dm_failed"
  | "material_failed"
  | "send_failed";

export function isFailure(step: Step["step"]): boolean {
  return step.endsWith("_failed");
}

// куда шаг переводит выдачу. Нет в списке: побочный шаг (ответ под комментом,
// нажатие после выдачи), состояние не меняет, где бы ни встал по времени
const NEXT: Partial<Record<Step["step"], Summary>> = {
  matched: "sending",
  dm_sent: "waiting_click",
  // новое нажатие начинает раунд: прошлая ошибка материала и просьба подписаться позади
  clicked: "clicked",
  follow_asked: "follow_asked",
  delivered: "delivered",
  repeat_comment: "repeat_comment",
  dm_failed: "dm_failed",
  material_failed: "material_failed",
  send_failed: "send_failed",
};

/** Где выдача сейчас, для строки ленты: шаги по порядку, как отдал api. */
export function summary(steps: Step[]): Summary | null {
  let state: Summary | null = null;
  for (const { step } of steps) {
    // материал получен: дальше ничего не меняет итог
    if (state === "delivered") break;
    state = NEXT[step] ?? state;
  }
  return state;
}

export type Stage = "dm" | "click" | "follow" | "material";
// unknown: о подписке просили, но выдали без проверки (Meta не ответила) или
// отправка упала раньше, чем подписку проверили
export type StageState = "done" | "current" | "failed" | "todo" | "unknown";

// этап, на котором выдача сейчас, и что с ним; до него всё сделано, после всё впереди
const AT: Record<Exclude<Summary, "repeat_comment" | "send_failed">, [Stage, StageState]> = {
  sending: ["dm", "current"],
  dm_failed: ["dm", "failed"],
  waiting_click: ["click", "current"],
  follow_asked: ["follow", "current"],
  clicked: ["material", "current"],
  material_failed: ["material", "failed"],
  delivered: ["material", "done"],
};

/** Что известно о подписке, когда выдача ушла дальше просьбы подписаться. Подписку
 * проверяют только при отправке материала: нажатие её ещё не подтверждает. */
function followState(now: Summary, steps: Step[]): StageState | null {
  if (now === "clicked") return "current";
  if (now === "material_failed" || now === "send_failed") return "unknown";
  if (now === "delivered") {
    const delivered = steps.findLast((s) => s.step === "delivered");
    return delivered?.follow === "following" ? "done" : "unknown";
  }
  return null;
}

/** Дорожка выдачи: этапы по порядку и где выдача сейчас. Выводится из summary(),
 * чтобы дорожка и надпись итога не разошлись. null: дорожки нет. */
export function stages(steps: Step[]): { stage: Stage; state: StageState }[] | null {
  const now = summary(steps);
  if (now === null || now === "repeat_comment") return null;
  const has = (step: Step["step"]) => steps.some((s) => s.step === step);
  // этап неудачи стёрся: до нажатия не ушёл директ, после него материал
  const [at, state] =
    now === "send_failed" ? ([has("clicked") ? "material" : "dm", "failed"] as const) : AT[now];
  // подписку показываем, только если о ней правда просили: включена ли проверка
  // в автоответе, из истории не узнать
  const asked = has("follow_asked");
  const order: Stage[] = asked
    ? ["dm", "click", "follow", "material"]
    : ["dm", "click", "material"];
  const index = order.indexOf(at);
  const track = order.map((stage, i): { stage: Stage; state: StageState } => ({
    stage,
    state: i < index ? "done" : i === index ? state : "todo",
  }));
  const follow = asked && index > order.indexOf("follow") ? followState(now, steps) : null;
  if (!follow) return track;
  return track.map((t) =>
    t.stage === "follow"
      ? { stage: t.stage, state: follow }
      : // нажал после просьбы: сейчас проверяем подписку, материал ещё впереди
        t.stage === "material" && follow === "current"
        ? { stage: t.stage, state: "todo" }
        : t,
  );
}

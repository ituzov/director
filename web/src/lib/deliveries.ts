/** Выдачи, как их отдаёт api (GET /autoreplies/deliveries), и вкладки этапов. */

export type DeliveryStage =
  | "sending"
  | "waiting_click"
  | "dm_failed"
  | "clicked"
  | "follow_asked"
  | "material_failed"
  | "delivered";

export type Delivery = {
  id: string;
  comment_id: string;
  person_id: string;
  // ник и текст коммента из входящих; null: там его уже нет
  username: string | null;
  text: string | null;
  autoreply_id: string;
  autoreply_name: string;
  keyword: string;
  stage: DeliveryStage;
  created_at: string;
};

export type DeliveryPage = { items: Delivery[]; next: string | null };
export type StageCounts = Record<DeliveryStage, number>;

// вкладки «Выдач»: на каких этапах сейчас люди. «Не дошло» это обе ошибки сразу;
// «отправляем» отдельной вкладки не имеет: это секунды, видно во «Всех»
const TABS = {
  all: [],
  waiting: ["waiting_click"],
  follow: ["follow_asked"],
  delivered: ["delivered"],
  failed: ["dm_failed", "material_failed"],
} as const satisfies Record<string, readonly DeliveryStage[]>;

export type Tab = keyof typeof TABS;
export const TAB_KEYS = Object.keys(TABS) as Tab[];

/** Вкладка из адреса; незнакомая значит «все». */
export function tabOf(value: string | string[] | undefined): Tab {
  // по списку ключей, а не `in`: тот видит и toString с прочим из прототипа
  return TAB_KEYS.find((tab) => tab === value) ?? "all";
}

/** Сколько людей на вкладке: сумма её этапов, у «всех» сумма всех. */
export function tabCount(tab: Tab, counts: StageCounts): number {
  const stages: readonly DeliveryStage[] =
    tab === "all" ? (Object.keys(counts) as DeliveryStage[]) : TABS[tab];
  return stages.reduce((sum, stage) => sum + (counts[stage] ?? 0), 0);
}

/** Параметры запроса выдач для вкладки: этап повторяется. */
export function stageQuery(tab: Tab): [string, string][] {
  return TABS[tab].map((stage) => ["stage", stage]);
}

export type Tone = "ok" | "warn" | "bad" | "muted";

// цвет точки этапа: внимание только там, где ждём человека или что-то не ушло
export const STAGE_TONE: Record<DeliveryStage, Tone> = {
  sending: "muted",
  waiting_click: "warn",
  dm_failed: "bad",
  clicked: "muted",
  follow_asked: "warn",
  material_failed: "bad",
  delivered: "ok",
};

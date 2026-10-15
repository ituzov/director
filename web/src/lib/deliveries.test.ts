import { describe, expect, it } from "vitest";

import { type StageCounts, stageQuery, tabCount, tabOf, waiting } from "./deliveries";

const counts: StageCounts = {
  sending: 1,
  waiting_click: 3,
  dm_failed: 2,
  clicked: 1,
  follow_asked: 4,
  material_failed: 5,
  delivered: 10,
};

describe("вкладки выдач", () => {
  it("вкладка из адреса, незнакомая значит все", () => {
    expect(tabOf("failed")).toBe("failed");
    expect(tabOf("toString")).toBe("all");
    expect(tabOf(["waiting", "failed"])).toBe("all");
    expect(tabOf(undefined)).toBe("all");
  });

  it("не дошло это обе ошибки сразу", () => {
    expect(stageQuery("failed")).toEqual([
      ["stage", "dm_failed"],
      ["stage", "material_failed"],
    ]);
    expect(tabCount("failed", counts)).toBe(7);
  });

  it("все без фильтра, счётчик по всем этапам", () => {
    expect(stageQuery("all")).toEqual([]);
    expect(tabCount("all", counts)).toBe(26);
  });

  it("получили только выданные", () => {
    expect(stageQuery("delivered")).toEqual([["stage", "delivered"]]);
    expect(tabCount("delivered", counts)).toBe(10);
  });

  it("ждут нажатия и ждут подписку по отдельности", () => {
    expect(stageQuery("waiting")).toEqual([["stage", "waiting_click"]]);
    expect(tabCount("follow", counts)).toBe(4);
  });
});

describe("сколько ждём человека", () => {
  const now = Date.parse("2026-10-16T12:00:00Z");
  const at = (hoursAgo: number) => new Date(now - hoursAgo * 3_600_000).toISOString();

  it.each<[string, Parameters<typeof waiting>[0], ReturnType<typeof waiting>]>([
    [
      "только что",
      { stage: "waiting_click", stage_at: at(0.5) },
      { unit: "hours", count: 0, stale: false },
    ],
    [
      "несколько часов",
      { stage: "waiting_click", stage_at: at(5) },
      { unit: "hours", count: 5, stale: false },
    ],
    [
      "сутки это уже дни",
      { stage: "follow_asked", stage_at: at(24) },
      { unit: "days", count: 1, stale: false },
    ],
    [
      "почти неделя",
      { stage: "waiting_click", stage_at: at(24 * 7 - 1) },
      { unit: "days", count: 6, stale: false },
    ],
    [
      "неделя: приглушаем",
      { stage: "waiting_click", stage_at: at(24 * 7) },
      { unit: "days", count: 7, stale: true },
    ],
    // часы разошлись: время этапа чуть впереди, не уходим в минус
    [
      "время в будущем",
      { stage: "waiting_click", stage_at: at(-1) },
      { unit: "hours", count: 0, stale: false },
    ],
    ["не ждём: получил", { stage: "delivered", stage_at: at(24 * 30) }, null],
    ["не ждём: отправляем", { stage: "clicked", stage_at: at(48) }, null],
  ])("%s", (_, d, want) => {
    expect(waiting(d, now)).toEqual(want);
  });
});

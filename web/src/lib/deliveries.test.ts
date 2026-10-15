import { describe, expect, it } from "vitest";

import { type StageCounts, stageQuery, tabCount, tabOf } from "./deliveries";

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

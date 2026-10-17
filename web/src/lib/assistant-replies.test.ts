import { describe, expect, it } from "vitest";

import {
  assistantTabOf,
  assistantTabQuery,
  errorKind,
  replyState,
  repliesQuery,
} from "./assistant-replies";

describe("что с комментом у ассистента", () => {
  it.each([
    ["answered", "sent", "sent ok"],
    ["answered", "sending", "sending warn"],
    // написал, но не дошло: неудача, а не «ответил»
    ["answered", "send_failed", "send_failed bad"],
    ["unsure", "done", "unsure warn"],
    ["not_mine", "done", "not_mine muted"],
    ["failed", "done", "failed bad"],
    ["limit", "done", "limit muted"],
    ["expired", "done", "expired muted"],
    ["paused", "done", "paused muted"],
    [null, "queued", "queued warn"],
    [null, "thinking", "thinking warn"],
  ] as const)("%s / %s", (outcome, stage, want) => {
    const { key, tone } = replyState({ outcome, stage });
    expect(`${key} ${tone}`).toBe(want);
  });
});

it("вкладка из адреса, незнакомая значит все", () => {
  expect(assistantTabOf("unsure")).toBe("unsure");
  expect(assistantTabOf("constructor")).toBe("all");
  expect(assistantTabOf(["missed", "unsure"])).toBe("all");
  expect(assistantTabQuery("all")).toEqual([]);
  expect(assistantTabQuery("missed")).toEqual([["tab", "missed"]]);
});

it("догрузка на вкладке спрашивает ту же вкладку", () => {
  // иначе «Ещё» на «Не ответил» тянуло бы строки всех вкладок
  const query = repliesQuery("acc", "missed", 50, "r1");
  expect([...query.entries()]).toEqual([
    ["account_id", "acc"],
    ["limit", "50"],
    ["before", "r1"],
    ["tab", "missed"],
  ]);
  expect(repliesQuery("acc", "all", 50).has("tab")).toBe(false);
});

it("код ошибки словами: известный, Meta числом, незнакомый", () => {
  expect(errorKind("key_rejected")).toBe("key_rejected");
  expect(errorKind("10")).toBe("meta");
  expect(errorKind("weird")).toBe("other");
});

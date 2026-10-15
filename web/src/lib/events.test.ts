import { describe, expect, it } from "vitest";

import { explain, type ResultCounts, resultCount, resultOf, resultQuery } from "./events";
import type { InboxItem } from "./inbox";

const counts: ResultCounts = { taken: 4, nobody: 2, skipped: 3, failed: 1, queued: 5 };

describe("вкладки всех событий", () => {
  it("вкладка из адреса, незнакомая значит все", () => {
    expect(resultOf("nobody")).toBe("nobody");
    expect(resultOf("queued")).toBe("all");
    expect(resultOf("constructor")).toBe("all");
    expect(resultOf(["taken", "failed"])).toBe("all");
    expect(resultOf(undefined)).toBe("all");
  });

  it("все включают неразобранные", () => {
    expect(resultCount("all", counts)).toBe(15);
    expect(resultQuery("all")).toEqual([]);
  });

  it("вкладка итога это свой счётчик и свой фильтр", () => {
    expect(resultCount("skipped", counts)).toBe(3);
    expect(resultQuery("failed")).toEqual([["result", "failed"]]);
  });
});

function item(over: Partial<InboxItem>): InboxItem {
  return {
    id: "e1",
    received_at: "2026-01-02T12:00:00Z",
    kind: "comment",
    person_id: "p1",
    username: "vasya",
    text: "гайд",
    attachment: null,
    media_id: "m1",
    comment_id: "c1",
    outcome: "done",
    reason: null,
    handled_by: null,
    handled_ref: null,
    ...over,
  };
}

// итог, цвет и объяснение одной строкой: так таблица сценариев читается целиком
function say(over: Partial<InboxItem>, name?: string): string {
  const { result, why } = explain(item(over), name);
  return [result.key, result.tone, why.key].join(" ");
}

const taken = { handled_by: "autoreplies", handled_ref: "a1" } as const;

describe("explain: чем кончилось и почему", () => {
  it.each<[string, Partial<InboxItem>, string | undefined, string]>([
    ["в очереди", { outcome: null }, undefined, "outcome.queued warn why.queued"],
    // упал и ждёт повтора: не «в ближайшие секунды»
    [
      "ждёт повтора",
      { outcome: null, reason: "ValueError" },
      undefined,
      "outcome.queued warn why.retrying",
    ],
    [
      "ошибка разбора",
      { outcome: "failed", reason: "ValueError" },
      undefined,
      "outcome.failed bad why.failed",
    ],
    [
      "свой коммент",
      { outcome: "skipped", reason: "own_comment" },
      undefined,
      "outcome.skipped.own_comment muted why.skipped.own_comment",
    ],
    [
      "аккаунт был отключён",
      { outcome: "skipped", reason: "account_inactive" },
      undefined,
      "outcome.skipped.account_inactive muted why.skipped.account_inactive",
    ],
    [
      "незнакомая причина пропуска",
      { outcome: "skipped", reason: "weird" },
      undefined,
      "outcome.skipped.other muted why.skipped.other",
    ],
    // только итог разбора: что было с выдачей дальше, здесь не рассказываем
    ["коммент взял автоответ", taken, "Гайд", "outcome.autoreply ok why.takenComment"],
    ["автоответа нет в списке", taken, undefined, "outcome.autoreplies ok why.takenNoName"],
    [
      "нажатие нашей кнопки",
      { ...taken, kind: "postback" },
      "Гайд",
      "outcome.autoreply ok why.takenPress",
    ],
    [
      "сообщение взял автоответ",
      { ...taken, kind: "message" },
      "Гайд",
      "outcome.autoreply ok why.taken",
    ],
    // нажал не тот или кнопка битая: не зелёным «взял автоответ»
    [
      "нажатие без выдачи",
      { kind: "postback", handled_by: "autoreplies", handled_ref: null },
      undefined,
      "outcome.buttonNoDelivery muted why.buttonNoDelivery",
    ],
    ["коммент никто не взял", {}, undefined, "outcome.noMatch muted why.noMatch"],
    [
      "чужая кнопка",
      { kind: "postback" },
      undefined,
      "outcome.foreignButton muted why.foreignButton",
    ],
    ["сообщение", { kind: "message" }, undefined, "outcome.noReply muted why.noReply"],
    ["другой обработчик", { handled_by: "assistant" }, undefined, "outcome.handled ok why.handled"],
  ])("%s", (_, over, name, want) => {
    expect(say(over, name)).toBe(want);
  });

  it("причина и название уходят в тексты", () => {
    expect(
      explain(item({ outcome: "failed", reason: "ValueError" }), undefined).why.params,
    ).toEqual({ reason: "ValueError" });
    expect(explain(item(taken), "Гайд").why.params).toEqual({ name: "Гайд" });
  });
});

import { describe, expect, it } from "vitest";

import { type Step, stages, summary } from "./inbox";

// шаги по порядку, как их отдаёт api; итогу важен код, дорожке ещё подписка у выдачи.
// "delivered:following" это выдача с проверенной подпиской
type Code = Step["step"] | "delivered:following" | "delivered:unknown";
function steps(...codes: Code[]): Step[] {
  return codes.map((code) => {
    const [step, follow] = code.split(":") as [Step["step"], string | undefined];
    return {
      step,
      at: "2026-01-02T12:00:00Z",
      autoreply_id: null,
      keyword: null,
      outcome: null,
      reason: null,
      follow: follow ?? null,
    };
  });
}

describe("summary: где выдача сейчас", () => {
  it.each<[string, Step["step"][], ReturnType<typeof summary>]>([
    ["истории нет", [], null],
    ["только сработал", ["matched"], "sending"],
    ["директ ушёл", ["matched", "dm_sent"], "waiting_click"],
    ["директ не ушёл", ["matched", "dm_failed"], "dm_failed"],
    ["неудача без этапа", ["matched", "send_failed"], "send_failed"],
    ["нажал", ["matched", "dm_sent", "clicked"], "clicked"],
    ["попросили подписаться", ["matched", "dm_sent", "clicked", "follow_asked"], "follow_asked"],
    ["материал не ушёл", ["matched", "dm_sent", "clicked", "material_failed"], "material_failed"],
    ["повторный коммент", ["repeat_comment"], "repeat_comment"],
    [
      "полная выдача с подпиской",
      ["matched", "dm_sent", "commented", "clicked", "follow_asked", "clicked", "delivered"],
      "delivered",
    ],
    // ответ под комментом это вежливость: его шаги итог не трогают, где бы ни встали
    ["ответ под комментом не ушёл", ["matched", "dm_sent", "comment_failed"], "waiting_click"],
    [
      "ответ под комментом пришёл после просьбы подписаться",
      ["matched", "dm_sent", "comment_failed", "clicked", "follow_asked", "commented"],
      "follow_asked",
    ],
    [
      "ответ под комментом не ушёл после нажатия",
      ["matched", "dm_sent", "clicked", "comment_failed"],
      "clicked",
    ],
    // новое нажатие начинает раунд: прошлая ошибка и просьба позади
    [
      "материал не ушёл, человек нажал снова",
      ["matched", "dm_sent", "clicked", "material_failed", "clicked"],
      "clicked",
    ],
    [
      "просьба, нажатие, снова просьба",
      ["matched", "dm_sent", "clicked", "follow_asked", "clicked", "follow_asked"],
      "follow_asked",
    ],
    [
      "просьба, нажатие, материал не ушёл",
      ["matched", "dm_sent", "clicked", "follow_asked", "clicked", "material_failed"],
      "material_failed",
    ],
    [
      "двойной тап, потом провал",
      ["matched", "dm_sent", "clicked", "clicked", "material_failed"],
      "material_failed",
    ],
    // получил материал: окончательно
    [
      "ошибка до выдачи не важна",
      ["matched", "dm_sent", "clicked", "material_failed", "clicked", "delivered"],
      "delivered",
    ],
    [
      "нажал после выдачи",
      ["matched", "dm_sent", "clicked", "delivered", "repeat_click"],
      "delivered",
    ],
    ["нажатие встало после выдачи", ["matched", "dm_sent", "delivered", "clicked"], "delivered"],
    // история без начала: журнал записал не всё
    ["нет срабатывания", ["dm_sent"], "waiting_click"],
    ["только ответ под комментом", ["commented"], null],
  ])("%s", (_, codes, want) => {
    expect(summary(steps(...codes))).toBe(want);
  });
});

describe("stages: дорожка выдачи", () => {
  const track = (...codes: Code[]) =>
    stages(steps(...codes))
      ?.map(({ stage, state }) => `${stage}:${state}`)
      .join(" ") ?? null;

  it.each<[string, Code[], string | null]>([
    ["истории нет", [], null],
    ["повторный коммент без дорожки", ["repeat_comment"], null],
    ["отправляем директ", ["matched"], "dm:current click:todo material:todo"],
    ["директ не ушёл", ["matched", "dm_failed"], "dm:failed click:todo material:todo"],
    ["ждём нажатия", ["matched", "dm_sent"], "dm:done click:current material:todo"],
    ["нажал", ["matched", "dm_sent", "clicked"], "dm:done click:done material:current"],
    [
      "попросили подписаться",
      ["matched", "dm_sent", "clicked", "follow_asked"],
      "dm:done click:done follow:current material:todo",
    ],
    [
      // подписку проверят при отправке материала: нажатие её ещё не подтверждает
      "нажал после просьбы подписаться",
      ["matched", "dm_sent", "clicked", "follow_asked", "clicked"],
      "dm:done click:done follow:current material:todo",
    ],
    [
      "получил без подписки",
      ["matched", "dm_sent", "clicked", "delivered"],
      "dm:done click:done material:done",
    ],
    [
      "получил с проверенной подпиской",
      ["matched", "dm_sent", "clicked", "follow_asked", "clicked", "delivered:following"],
      "dm:done click:done follow:done material:done",
    ],
    [
      "получил без проверки подписки",
      ["matched", "dm_sent", "clicked", "follow_asked", "clicked", "delivered:unknown"],
      "dm:done click:done follow:unknown material:done",
    ],
    [
      "после просьбы отправка упала без этапа",
      ["matched", "dm_sent", "clicked", "follow_asked", "clicked", "send_failed"],
      "dm:done click:done follow:unknown material:failed",
    ],
    [
      "после просьбы материал не ушёл",
      ["matched", "dm_sent", "clicked", "follow_asked", "clicked", "material_failed"],
      "dm:done click:done follow:unknown material:failed",
    ],
    [
      "материал не ушёл",
      ["matched", "dm_sent", "clicked", "material_failed"],
      "dm:done click:done material:failed",
    ],
    [
      "неудача без этапа до нажатия",
      ["matched", "send_failed"],
      "dm:failed click:todo material:todo",
    ],
    [
      "неудача без этапа после нажатия",
      ["matched", "dm_sent", "clicked", "send_failed"],
      "dm:done click:done material:failed",
    ],
  ])("%s", (_, codes, want) => {
    expect(track(...codes)).toBe(want);
  });
});

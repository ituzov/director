import { createFormatter } from "next-intl";
import { describe, expect, it } from "vitest";

import { shortTime } from "./labels";

// событие в 20:30 UTC, страницу открыли в 21:00 UTC
const at = new Date("2026-10-15T20:30:00Z");
const now = Date.parse("2026-10-15T21:00:00Z");

function format(timeZone: string) {
  return createFormatter({ locale: "ru", timeZone });
}

describe("shortTime: сегодня в поясе форматтера, а не среды", () => {
  it("в UTC это сегодня: часы", () => {
    expect(shortTime(at, now, format("UTC"))).toBe("20:30");
  });

  it("в Москве уже следующий день: дата", () => {
    // 23:30 15-го против 00:00 16-го
    expect(shortTime(at, now, format("Europe/Moscow"))).toMatch(/^15 окт/);
  });
});

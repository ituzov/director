import { describe, expect, it } from "vitest";

import { formErrorsOf, isKnownProvider, keyError, nameError } from "./ai";

const KEY = "sk-ant-api03-0123456789abcdefWXYZ";

describe("правила ключа как у api", () => {
  it("рабочий ключ проходит, пробелы по краям не считаются", () => {
    expect(keyError(KEY)).toBeNull();
    expect(keyError(`  ${KEY}\n`)).toBeNull();
  });

  it("короткий, длинный и с лишними символами", () => {
    expect(keyError("sk-short")).toBe("KeyTooShort");
    expect(keyError("k".repeat(501))).toBe("KeyTooLong");
    // из копирования: кириллица, неразрывный пробел, нулевая ширина
    expect(keyError(KEY.slice(0, -1) + "Ж")).toBe("KeyInvalidChars");
    expect(keyError(KEY.slice(0, 10) + " " + KEY.slice(10))).toBe("KeyInvalidChars");
    expect(keyError(KEY + "​")).toBe("KeyInvalidChars");
  });

  it("название до 60 символов", () => {
    expect(nameError("x".repeat(60))).toBeNull();
    expect(nameError("x".repeat(61))).toBe("NameTooLong");
  });
});

describe("ошибки api по полям формы", () => {
  it("имя ошибки сервиса к своему полю", () => {
    expect(formErrorsOf("KeyRejected")).toEqual({ key: "KeyRejected" });
    expect(formErrorsOf("KeyInvalidChars")).toEqual({ key: "KeyInvalidChars" });
    expect(formErrorsOf("UnknownProvider")).toEqual({ provider: "UnknownProvider" });
  });

  it("ошибки схемы по loc и типу", () => {
    const detail = [
      { loc: ["body", "key"], type: "string_too_long" },
      { loc: ["body", "name"], type: "string_too_long" },
    ];
    expect(formErrorsOf(detail)).toEqual({ key: "KeyTooLong", name: "NameTooLong" });
    // ключ из одних пробелов схема режет как слишком короткий
    expect(formErrorsOf([{ loc: ["body", "key"], type: "string_too_short" }])).toEqual({
      key: "KeyTooShort",
    });
  });

  it("незнакомое не превращается в ошибку поля", () => {
    expect(formErrorsOf("BaseUrlNotAllowed")).toEqual({});
    expect(formErrorsOf(null)).toEqual({});
  });
});

it("неизвестный провайдер отличается от известного", () => {
  expect(isKnownProvider("timeweb")).toBe(true);
  expect(isKnownProvider("openrouter")).toBe(false);
});

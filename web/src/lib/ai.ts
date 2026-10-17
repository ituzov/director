/** Подключения к нейросетям, как их отдают ручки /ai. Ключа здесь нет и не
 * будет: api отдаёт только последние 4 символа. */

// поломка, которая сама не пройдёт: её показывает карточка подключения
export type CardError = "key_rejected" | "no_funds" | "key_unreadable";

// итог только что сделанной проверки ключа; имена совпадают с ключами
// Ai.check в messages
export type CheckResult =
  "ok" | CardError | "rate_limited" | "timeout" | "server" | "bad_response" | "model_missing";

/** Задача, которая идёт через подключение: «Ассистент: ответ · 2 аккаунта». */
export type AiTask = {
  purpose: string;
  // сколько настроек задачи на этом подключении (общая и по аккаунтам)
  scopes: number;
  models: string[];
  // провайдер сказал, что модели нет: выбирают другую в самой задаче
  model_missing: boolean;
};

export type AiConnection = {
  id: string;
  provider: string;
  name: string;
  key_hint: string;
  base_url: string | null;
  // последний итог про этот ключ успешный
  checked_at: string | null;
  error_code: CardError | null;
  error_at: string | null;
  created_at: string;
  tasks: AiTask[];
};

/** Ответ создания, замены ключа и «Проверить ещё раз»: карточка и итог проверки.
 * Итог отдельно: разовый сбой карточку не меняет, а человеку нужно знать, что
 * проверка не прошла. */
export type AiChecked = { connection: AiConnection; check: CheckResult };

export type AiProvider = { kind: string; needs_base_url: boolean };

/** Провайдеры, которых знает эта версия web, и где владелец берёт ключ. У
 * Timeweb точный адрес раздела снаружи не проверить: панель целиком, а путь до
 * ключей словами в подсказке. Новый провайдер добавляется сюда и в реестр api. */
export const PROVIDERS = [
  { kind: "anthropic", keysUrl: "https://platform.claude.com/settings/keys" },
  { kind: "timeweb", keysUrl: "https://timeweb.cloud/my" },
] as const;
export type ProviderKind = (typeof PROVIDERS)[number]["kind"];

/** Вид, который записала версия api новее: показываем как есть и не даём
 * проверять и менять, api его не знает. */
export function isKnownProvider(kind: string): kind is ProviderKind {
  return PROVIDERS.some((p) => p.kind === kind);
}

// имена совпадают с ключами Ai.connect.errors в messages
export type FormError =
  | "UnknownProvider"
  | "NameTooLong"
  | "KeyTooShort"
  | "KeyTooLong"
  | "KeyInvalidChars"
  | "KeyRejected";
export type FormErrors = Partial<Record<"provider" | "name" | "key", FormError>>;

// те же правила, что у api (schemas.py и service._key): ошибка видна сразу
const MIN_KEY = 20;
const MAX_KEY = 500;
const MAX_NAME = 60;
const PRINTABLE_ASCII = /^[\x21-\x7e]+$/;

export function keyError(value: string): FormError | null {
  const key = value.trim();
  if (key.length < MIN_KEY) return "KeyTooShort";
  if (key.length > MAX_KEY) return "KeyTooLong";
  return PRINTABLE_ASCII.test(key) ? null : "KeyInvalidChars";
}

export function nameError(value: string): FormError | null {
  return value.trim().length > MAX_NAME ? "NameTooLong" : null;
}

const KEY_ERRORS = ["KeyTooShort", "KeyInvalidChars", "KeyRejected"] as const;

type PydanticError = { loc?: unknown[]; type?: unknown } | null;

/** Ответ 422 от /ai по полям формы: имя ошибки от сервиса или список ошибок
 * схемы pydantic с loc ["body", поле]. Незнакомое: пусто, решает вызывающий. */
export function formErrorsOf(detail: unknown): FormErrors {
  if (detail === "UnknownProvider") return { provider: "UnknownProvider" };
  const keyCode = KEY_ERRORS.find((code) => code === detail);
  if (keyCode) return { key: keyCode };
  if (!Array.isArray(detail)) return {};
  const errors: FormErrors = {};
  for (const d of detail as PydanticError[]) {
    const field = d?.loc?.[1];
    if (field === "provider") errors.provider = "UnknownProvider";
    if (field === "name") errors.name = "NameTooLong";
    // у ключа схема проверяет только длину: короткий или длинный
    if (field === "key") errors.key = d?.type === "string_too_long" ? "KeyTooLong" : "KeyTooShort";
  }
  return errors;
}

/** Состояние карточки, про которое итог проверки: ключ и последний итог на ней. */
export function stampOf(connection: AiConnection): string {
  return [connection.key_hint, connection.checked_at, connection.error_code].join("|");
}

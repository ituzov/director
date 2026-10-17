"use server";

// Ключ приходит только внутри FormData: Next в dev печатает аргументы серверных
// функций в терминал, и ключ обычным аргументом оказался бы в логе целиком.
// Пустое название заменяет именем провайдера форма: getTranslations в серверном
// действии next-intl не умеет (язык он берёт из next/root-params, а там его нет)

import { refresh } from "next/cache";
import { redirect } from "next/navigation";

import {
  type AiChecked,
  type AiConnection,
  type CheckResult,
  type FormErrors,
  formErrorsOf,
  stampOf,
} from "@/lib/ai";
import { ApiError, apiFetch } from "@/lib/api";
import { getToken } from "@/lib/session";

export type ConnectState = {
  errors?: FormErrors;
  // подключение сохранено, но ключ не проверен или с поломкой: форма говорит почему
  saved?: Exclude<CheckResult, "ok">;
};

/** Подключить провайдера. Ключ работает: на список. Провайдер ключ не принял:
 * ошибка у поля, ничего не сохранено. Иначе сохранено, и форма объясняет, что не так. */
export async function connect(_prev: ConnectState, form: FormData): Promise<ConnectState> {
  const provider = text(form, "provider");
  let checked: AiChecked;
  try {
    checked = await apiFetch<AiChecked>("/ai/connections", {
      method: "POST",
      body: {
        provider,
        name: text(form, "name"),
        key: text(form, "key"),
      },
      token: await getToken(),
    });
  } catch (e) {
    const errors = e instanceof ApiError && e.status === 422 ? formErrorsOf(e.detail) : {};
    if (Object.keys(errors).length > 0) return { errors };
    throw e;
  }
  // redirect бросает исключение, поэтому он вне try
  if (checked.check === "ok") redirect("/settings/ai");
  return { saved: checked.check };
}

/** Итог проверки и состояние карточки, про которое он: строка итога видна, только
 * пока карточка в этом же состоянии. Иначе «Ключ работает» висело бы рядом с
 * «Ключ не принят», который записал фоновый вызов позже. */
export type Checked = { check: CheckResult; stamp: string };

// подключение удалили в другой вкладке: список перерисуется без него
type Gone = { gone: true };

/** «Проверить ещё раз». Ключа здесь нет, только id. */
export async function recheck(id: string): Promise<Checked | Gone> {
  try {
    const checked = await apiFetch<AiChecked>(`/ai/connections/${id}/check`, {
      method: "POST",
      token: await getToken(),
    });
    return { check: checked.check, stamp: stampOf(checked.connection) };
  } catch (e) {
    if (isGone(e)) return { gone: true };
    throw e;
  } finally {
    refresh();
  }
}

export type EditResult = { errors: FormErrors } | Partial<Checked> | Gone;

/** Окно «Изменить»: сначала новый ключ, если ввели, потом название. Ключ не
 * приняли: не меняется ничего, и название тоже. */
export async function editConnection(form: FormData): Promise<EditResult> {
  const id = text(form, "id");
  const key = text(form, "key");
  const name = text(form, "name");
  const token = await getToken();
  try {
    let checked: Partial<Checked> = {};
    if (key) {
      const result = await apiFetch<AiChecked>(`/ai/connections/${id}/key`, {
        method: "PUT",
        body: { key },
        token,
      });
      checked = { check: result.check, stamp: stampOf(result.connection) };
    }
    if (name !== text(form, "current_name")) {
      const connection = await apiFetch<AiConnection>(`/ai/connections/${id}`, {
        method: "PATCH",
        body: { name },
        token,
      });
      if (checked.check) checked.stamp = stampOf(connection);
    }
    return checked;
  } catch (e) {
    if (isGone(e)) return { gone: true };
    const errors = e instanceof ApiError && e.status === 422 ? formErrorsOf(e.detail) : {};
    if (Object.keys(errors).length > 0) return { errors };
    throw e;
  } finally {
    refresh();
  }
}

/** «Отключить»: задачи на нём станут «не настроенными», журнал вызовов останется. */
export async function disconnect(id: string): Promise<void> {
  try {
    await apiFetch(`/ai/connections/${id}`, { method: "DELETE", token: await getToken() });
  } catch (e) {
    // уже удалили в другой вкладке: итог тот же
    if (!isGone(e)) throw e;
  }
  refresh();
}

function text(form: FormData, key: string): string {
  return String(form.get(key) ?? "").trim();
}

function isGone(e: unknown): boolean {
  return e instanceof ApiError && e.status === 404;
}

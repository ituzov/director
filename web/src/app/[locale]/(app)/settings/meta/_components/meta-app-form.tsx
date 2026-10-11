"use client";

import { Form } from "@base-ui/react/form";
import { useFormatter, useTranslations } from "next-intl";
import { startTransition, useActionState, useState } from "react";

import { FormField } from "@/components/form-field";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useInBrowser } from "@/hooks/use-in-browser";
import type { MetaApp } from "@/lib/meta-app";

import { type MetaAppError, saveMetaApp, type MetaAppState } from "../actions";

const INITIAL: MetaAppState = {};
// те же правила, что у api: ошибка видна сразу, без запроса
const APP_ID = /^[0-9]{1,32}$/;
const APP_SECRET = /^[0-9a-fA-F]{32}$/;

export function MetaAppForm({ metaApp }: { metaApp: MetaApp | null }) {
  const t = useTranslations("MetaApp");
  const format = useFormatter();
  const [state, action, pending] = useActionState(saveMetaApp, INITIAL);
  // секрет задан: поле закрыто, пока не нажали «Заменить»
  const [replacing, setReplacing] = useState(metaApp === null);
  // время в поясе браузера, а он известен только в браузере: на сервере строку не рисуем,
  // иначе разметка сервера и браузера разойдётся
  const inBrowser = useInBrowser();

  const fieldErrors = Object.fromEntries(
    Object.entries(state.errors ?? {}).map(([field, code]) => [field, t(`errors.${code}`)]),
  );
  const check = (pattern: RegExp, error: MetaAppError) => (value: unknown) => {
    const text = String(value ?? "").trim();
    if (!text) return t("errors.Required");
    return pattern.test(text) ? null : t(`errors.${error}`);
  };

  return (
    <Form
      method="post"
      errors={fieldErrors}
      // не action, а onSubmit: при <form action> React 19 сбрасывает поля после ошибки
      onSubmit={(event) => {
        event.preventDefault();
        const data = new FormData(event.currentTarget);
        startTransition(() => action(data));
      }}
      className="grid gap-6"
    >
      <div className="grid gap-4">
        <FormField
          name="app_id"
          label={t("appId")}
          description={t("appIdHint")}
          validate={check(APP_ID, "InvalidAppId")}
        >
          <Input defaultValue={metaApp?.app_id} inputMode="numeric" autoComplete="off" />
        </FormField>
        {replacing ? (
          <FormField
            name="app_secret"
            label={t("appSecret")}
            description={t("appSecretHint")}
            validate={check(APP_SECRET, "InvalidAppSecret")}
          >
            <Input type="password" autoComplete="off" />
          </FormField>
        ) : (
          <FormField name="app_secret" label={t("appSecret")} description={t("secretSet")}>
            <div className="flex gap-2">
              {/* disabled не попадает в FormData: action поймёт, что секрет не меняем */}
              <Input value="••••••••••••" disabled readOnly />
              <Button type="button" variant="outline" onClick={() => setReplacing(true)}>
                {t("replace")}
              </Button>
            </div>
          </FormField>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-4">
        <Button type="submit" disabled={pending}>
          {t("submit")}
        </Button>
        {metaApp &&
          (inBrowser ? (
            <p className="text-sm text-muted-foreground">
              {t("updatedAt", {
                date: format.dateTime(new Date(metaApp.updated_at), {
                  dateStyle: "medium",
                  timeStyle: "short",
                }),
              })}
            </p>
          ) : (
            // до гидрации пояс браузера неизвестен: держим место под строку
            <Skeleton className="h-4 w-56" />
          ))}
      </div>
    </Form>
  );
}

/** Скелет той же формы: пока данные едут, поля стоят на своих местах. */
export function MetaAppFormSkeleton() {
  return (
    <div className="grid gap-6">
      <div className="grid gap-4">
        {[0, 1].map((i) => (
          <div key={i} className="grid gap-2">
            <Skeleton className="h-4 w-36" />
            <Skeleton className="h-10 w-full md:h-9" />
            <Skeleton className="h-3 w-64 max-w-full" />
          </div>
        ))}
      </div>
      <Skeleton className="h-10 w-28 md:h-9" />
    </div>
  );
}

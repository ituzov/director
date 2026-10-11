"use client";

import { Form } from "@base-ui/react/form";
import { useTranslations } from "next-intl";
import { startTransition, useActionState } from "react";

import { FormField } from "@/components/form-field";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import { setup, type SetupState } from "../actions";

const INITIAL: SetupState = {};
const MIN_PASSWORD_LENGTH = 8;
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function SetupForm({ token }: { token?: string }) {
  const t = useTranslations("Setup");
  const [state, action, pending] = useActionState(setup, INITIAL);

  // коды ошибок из action в тексты; токен из ссылки скрыт, его ошибка идёт в общий блок
  const fieldErrors = Object.fromEntries(
    Object.entries(state.errors ?? {})
      .filter(([field]) => !(token && field === "token"))
      .map(([field, code]) => [field, t(`errors.${code}`)]),
  );
  const formError = state.error ?? (token ? state.errors?.token : undefined);

  const required = (value: unknown) => (String(value ?? "").trim() ? null : t("errors.Required"));

  return (
    <Form
      method="post"
      errors={fieldErrors}
      // не action, а onSubmit: при <form action> React 19 сбрасывает поля, и пароли пропадали бы
      onSubmit={(event) => {
        event.preventDefault();
        const data = new FormData(event.currentTarget);
        startTransition(() => action(data));
      }}
      className="grid gap-6"
    >
      <div className="grid gap-4">
        {token ? (
          <input type="hidden" name="token" value={token} />
        ) : (
          <FormField
            name="token"
            label={t("token")}
            description={t("tokenHint")}
            validate={required}
          >
            <Input autoComplete="off" />
          </FormField>
        )}
        <FormField
          name="email"
          label={t("email")}
          validate={(value) =>
            required(value) ?? (EMAIL.test(String(value)) ? null : t("errors.InvalidEmail"))
          }
        >
          {/* type="text": у type="email" своя проверка браузера с его пузырём */}
          <Input inputMode="email" autoComplete="email" />
        </FormField>
        <FormField
          name="password"
          label={t("password")}
          validate={(value) =>
            required(value) ??
            (String(value).length < MIN_PASSWORD_LENGTH ? t("errors.WeakPassword") : null)
          }
        >
          <Input type="password" maxLength={1024} autoComplete="new-password" />
        </FormField>
        <FormField
          name="confirm"
          label={t("confirm")}
          validate={(value, values) =>
            required(value) ?? (value === values.password ? null : t("errors.PasswordMismatch"))
          }
        >
          <Input type="password" autoComplete="new-password" />
        </FormField>
        {formError && (
          <p role="alert" className="text-sm text-destructive">
            {t(`errors.${formError}`)}
          </p>
        )}
      </div>
      <Button type="submit" className="w-full" disabled={pending}>
        {t("submit")}
      </Button>
    </Form>
  );
}

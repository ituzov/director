"use client";

import { Form } from "@base-ui/react/form";
import { useTranslations } from "next-intl";
import { startTransition, useActionState } from "react";

import { FormField } from "@/components/form-field";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import { login, type LoginState } from "../actions";

const INITIAL: LoginState = {};

export function LoginForm() {
  const t = useTranslations("Login");
  const [state, action, pending] = useActionState(login, INITIAL);

  const required = (value: unknown) => (String(value ?? "").trim() ? null : t("errors.Required"));

  return (
    <Form
      method="post"
      // не action, а onSubmit: при <form action> React 19 сбрасывает поля после ошибки
      onSubmit={(event) => {
        event.preventDefault();
        const data = new FormData(event.currentTarget);
        startTransition(() => action(data));
      }}
      className="grid gap-6"
    >
      <div className="grid gap-4">
        <FormField name="email" label={t("email")} validate={required}>
          <Input inputMode="email" autoComplete="email" />
        </FormField>
        <FormField name="password" label={t("password")} validate={required}>
          <Input type="password" maxLength={1024} autoComplete="current-password" />
        </FormField>
        {/* неверная почта или пароль: не говорим, что именно, поэтому общий блок, а не поле */}
        {state.error && (
          <p role="alert" className="text-sm text-destructive">
            {t(`errors.${state.error}`)}
          </p>
        )}
      </div>
      <Button type="submit" className="w-full" disabled={pending}>
        {t("submit")}
      </Button>
    </Form>
  );
}

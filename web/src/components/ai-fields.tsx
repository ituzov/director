"use client";

import { useTranslations } from "next-intl";

import { FormField } from "@/components/form-field";
import { Input } from "@/components/ui/input";
import { keyError, nameError } from "@/lib/ai";

// Поля подключения к нейросети: форма подключения и окно «Изменить» проверяют
// одинаково, правила в lib/ai.ts рядом с api

type KeyFieldProps = {
  label: string;
  description: string;
  // в окне «Изменить» пустой ключ значит «оставить прежний»
  optional?: boolean;
};

export function KeyField({ label, description, optional = false }: KeyFieldProps) {
  const t = useTranslations("Ai.connect.errors");
  return (
    <FormField
      name="key"
      label={label}
      description={description}
      validate={(value) => {
        const key = String(value ?? "");
        if (optional && !key.trim()) return null;
        const code = keyError(key);
        return code && t(code);
      }}
    >
      {/* new-password: Chrome не подставит сюда сохранённый пароль от Директора и не
          предложит запомнить ключ как пароль; метки просят о том же менеджеры паролей */}
      <Input
        type="password"
        autoComplete="new-password"
        spellCheck={false}
        data-1p-ignore
        data-lpignore="true"
        data-bwignore
      />
    </FormField>
  );
}

type NameFieldProps = {
  label: string;
  description?: string;
  defaultValue?: string;
  placeholder?: string;
};

export function NameField({ label, description, defaultValue, placeholder }: NameFieldProps) {
  const t = useTranslations("Ai.connect.errors");
  return (
    <FormField
      name="name"
      label={label}
      description={description}
      validate={(value) => {
        const code = nameError(String(value ?? ""));
        return code && t(code);
      }}
    >
      <Input defaultValue={defaultValue} placeholder={placeholder} autoComplete="off" />
    </FormField>
  );
}

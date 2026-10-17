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
      {/* не type="password": поле-пароль рядом с текстовым Safari принимает за вход и
          предлагает сохранить ключ как пароль, autocomplete он не слушает. Точки рисует
          стиль; где его нет, ключ при вводе виден, это ввод один раз на своём экране.
          Метки просят менеджеры паролей не трогать поле */}
      <Input
        type="text"
        autoComplete="off"
        autoCapitalize="off"
        spellCheck={false}
        data-1p-ignore
        data-lpignore="true"
        data-bwignore
        className="[-webkit-text-security:disc]"
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

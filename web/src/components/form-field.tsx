"use client";

import { Field } from "@base-ui/react/field";

import { Label } from "@/components/ui/label";

type Props = {
  name: string;
  label: string;
  description?: string;
  validate?: React.ComponentProps<typeof Field.Root>["validate"];
  children: React.ReactNode;
};

/**
 * Поле формы: подпись, контрол, подсказка и ошибка под ним. Живёт внутри Form из Base UI,
 * ошибки сервера приходят через errors у Form по имени поля.
 * Проверки только через validate: у встроенных (required, minLength) браузер
 * показывает свои пузыри на своём языке.
 */
export function FormField({ name, label, description, validate, children }: Props) {
  return (
    <Field.Root name={name} validate={validate} className="grid gap-2">
      <Field.Label render={<Label />}>{label}</Field.Label>
      {children}
      {description && (
        <Field.Description className="text-muted-foreground text-xs">
          {description}
        </Field.Description>
      )}
      <Field.Error className="text-destructive text-sm" />
    </Field.Root>
  );
}

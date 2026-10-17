"use client";

import { useTranslations } from "next-intl";
import { useEffect, useId, useState } from "react";

import {
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
} from "@/components/ui/combobox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Link } from "@/i18n/navigation";
import { type AiConnection, isKnownProvider } from "@/lib/ai";
import { cn } from "@/lib/utils";

import { loadModels, type ModelsResult } from "../actions";

type Props = {
  // null: подключения видит только владелец, остальным модель текстом
  connections: AiConnection[] | null;
  connectionId: string | null;
  model: string | null;
  modelMissing: boolean;
  error?: string;
};

// селект в виде поля: как Input, со стрелкой браузера
const SELECT =
  "h-10 w-full min-w-0 rounded-lg border border-input bg-transparent px-2.5 text-base outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 md:h-9 md:text-sm";

/** Подключение (провайдер с ключом) и модель этого подключения. Модель можно
 * вписать и руками: у Timeweb моделей десятки, список подсказывает, а не держит. */
export function ModelPicker({ connections, connectionId, model, modelMissing, error }: Props) {
  const t = useTranslations("Assistants.form.model");
  const tProviders = useTranslations("Ai.providers");
  const listId = useId();
  const [chosen, setChosen] = useState(connectionId ?? connections?.[0]?.id ?? "");
  // список вместе с подключением, для которого он: сменили подключение, и старый
  // список сам собой становится «ещё грузится», сбрасывать его не нужно
  const [loaded, setLoaded] = useState<{ for: string; result: ModelsResult } | null>(null);
  const models = loaded?.for === chosen ? loaded.result : null;

  useEffect(() => {
    if (!chosen) return;
    let current = true;
    void loadModels(chosen)
      .catch((): ModelsResult => ({ models: [], error: "server" }))
      .then((result) => current && setLoaded({ for: chosen, result }));
    // сменили подключение раньше ответа: опоздавший список не нужен
    return () => {
      current = false;
    };
  }, [chosen]);

  if (connections === null) {
    // участник: выбрать не может, видит, на чём отвечает ассистент
    return (
      <p className="text-sm text-muted-foreground">
        {model ? t("readonly", { model }) : t("none")}
      </p>
    );
  }
  if (connections.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        {t.rich("noConnections", {
          link: (chunks) => (
            <Link href="/settings/ai/connect" className="text-foreground underline">
              {chunks}
            </Link>
          ),
        })}
      </p>
    );
  }
  const current = connections.find((c) => c.id === chosen);

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div className="grid content-start gap-2">
        <Label htmlFor={`${listId}-connection`}>{t("connection")}</Label>
        <select
          id={`${listId}-connection`}
          name="connection_id"
          value={chosen}
          onChange={(e) => setChosen(e.target.value)}
          aria-invalid={Boolean(error)}
          className={SELECT}
        >
          {connections.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name} · {isKnownProvider(c.provider) ? tProviders(c.provider) : c.provider}
            </option>
          ))}
        </select>
        {current?.error_code && (
          <p className="text-sm text-destructive" role="alert">
            {t("broken")}
          </p>
        )}
        {error && (
          <p className="text-sm text-destructive" role="alert">
            {error}
          </p>
        )}
      </div>
      <div className="grid content-start gap-2">
        <Label htmlFor={`${listId}-model`}>{t("model")}</Label>
        {models && !models.error && models.models.length > 0 ? (
          <Combobox
            // другое подключение: другие модели, прошлый выбор к ним не относится
            key={chosen}
            name="model"
            items={withCurrent(
              models.models.map((m) => m.id),
              chosen === connectionId ? model : null,
            )}
            defaultValue={chosen === connectionId ? model : null}
          >
            <ComboboxInput
              id={`${listId}-model`}
              placeholder={t("placeholder")}
              className="w-full font-mono"
            />
            <ComboboxContent>
              <ComboboxEmpty>{t("nothing")}</ComboboxEmpty>
              <ComboboxList>
                {(id: string) => (
                  <ComboboxItem key={id} value={id} className="font-mono">
                    {id}
                  </ComboboxItem>
                )}
              </ComboboxList>
            </ComboboxContent>
          </Combobox>
        ) : (
          // список ещё едет или не загрузился: модель можно вписать руками
          <Input
            id={`${listId}-model`}
            name="model"
            defaultValue={model ?? ""}
            autoComplete="off"
            spellCheck={false}
            placeholder={t("placeholder")}
            className="font-mono"
          />
        )}
        <p
          className={cn(
            "text-xs",
            models?.error || modelMissing ? "text-destructive" : "text-muted-foreground",
          )}
        >
          {modelMissing
            ? t("missing")
            : models === null
              ? t("loading")
              : models.error
                ? t("loadFailed")
                : t("count", { count: models.models.length })}
        </p>
      </div>
    </div>
  );
}

/** Нынешняя модель в списке, даже если провайдер её больше не отдаёт: иначе поле
 * молча опустело бы, и сохранение выбросило бы модель. */
function withCurrent(ids: string[], current: string | null): string[] {
  return current && !ids.includes(current) ? [current, ...ids] : ids;
}

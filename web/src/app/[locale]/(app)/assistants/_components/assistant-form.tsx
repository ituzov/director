"use client";

import { Field } from "@base-ui/react/field";
import { Form } from "@base-ui/react/form";
import { BookOpen, MapPin, MessageSquareText, ScrollText } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import {
  startTransition,
  useActionState,
  useEffect,
  useOptimistic,
  useRef,
  useState,
  useTransition,
} from "react";

import { FormField } from "@/components/form-field";
import { Page, Panel } from "@/components/page";
import { PostPicker } from "@/components/post-picker";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Link } from "@/i18n/navigation";
import type { AiConnection } from "@/lib/ai";
import {
  type Assistant,
  type AssistantConflict,
  type AssistantMode,
  LIMITS,
} from "@/lib/assistants";
import { cn } from "@/lib/utils";

import {
  loadMedia,
  loadSelectedMedia,
  type SaveState,
  saveAssistant,
  setEnabled,
} from "../actions";
import { ModelPicker } from "./model-picker";
import { TryPanel } from "./try-panel";

const INITIAL: SaveState = {};

const TEXTAREA =
  "w-full rounded-lg border border-input bg-transparent px-2.5 py-2 text-base leading-relaxed transition-colors outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 aria-invalid:border-destructive md:text-sm";

const MODES: AssistantMode[] = ["direct", "comment", "combo"];

type Props = {
  assistant: Assistant | null;
  // аккаунт нового; у правимого свой, в assistant.account_id
  accountId: string | null;
  // null: подключения видит только владелец
  connections: AiConnection[] | null;
  // новый подставляет подключение и модель последнего ассистента аккаунта
  defaults: { connectionId: string | null; model: string | null };
  // менять может владелец: остальным форма только для чтения
  canEdit: boolean;
};

/** Новый переход даёт новый bfcacheId и чистую форму, как у автоответов. */
export function AssistantForm(props: Props) {
  const { bfcacheId } = useRouter();
  return <AssistantFormFields key={bfcacheId} {...props} />;
}

function AssistantFormFields({ assistant, accountId, connections, defaults, canEdit }: Props) {
  const t = useTranslations("Assistants.form");
  const [state, action, pending] = useActionState(saveAssistant, INITIAL);
  const [scope, setScope] = useState(assistant?.scope ?? "all");
  const [mode, setMode] = useState<AssistantMode>(assistant?.mode ?? "direct");
  const archived = Boolean(assistant?.archived_at);
  const readonly = !canEdit || archived;
  const formRef = useRef<HTMLFormElement>(null);

  // api вернул ошибку: ведём к самой верхней, иначе её не видно под кнопкой
  useEffect(() => {
    if (!state.errors && !state.conflict && !state.failed) return;
    formRef.current
      ?.querySelector<HTMLElement>('[aria-invalid="true"], [role="alert"]')
      ?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [state]);

  const errors = state.errors ?? {};
  const fieldErrors = Object.fromEntries(
    Object.entries(errors).map(([field, code]) => [field, t(`errors.${code}`)]),
  );
  const required = (value: unknown) => (String(value ?? "").trim() ? null : t("errors.required"));

  return (
    <Form
      ref={formRef}
      method="post"
      errors={fieldErrors}
      // не action, а onSubmit: при <form action> React 19 сбрасывает поля после ошибки
      onSubmit={(event) => {
        event.preventDefault();
        const data = new FormData(event.currentTarget);
        startTransition(() => action(data));
      }}
    >
      <Page width="wide">
        {assistant ? (
          <input type="hidden" name="id" value={assistant.id} />
        ) : (
          <input type="hidden" name="account_id" value={accountId ?? ""} />
        )}
        {(archived || !canEdit) && (
          <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
            {archived ? t("archivedNotice") : t("ownerOnly")}
          </p>
        )}

        {/* от lg проверка справа и едет вместе с экраном, ниже уходит под форму */}
        <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_24rem]">
          {/* disabled у fieldset закрывает все поля разом: участнику и архивному */}
          <fieldset disabled={readonly} className="grid min-w-0 gap-6">
            <Panel
              icon={MessageSquareText}
              title={assistant?.name ?? t("newTitle")}
              description={t("description")}
              actions={assistant && canEdit && !archived ? <Pause assistant={assistant} /> : null}
            >
              <FormField name="name" label={t("name")} validate={required}>
                <Input defaultValue={assistant?.name} maxLength={LIMITS.name} autoComplete="off" />
              </FormField>
              {assistant && (
                <p className="text-sm text-muted-foreground tabular-nums">
                  {t("today", {
                    answered: assistant.today.answered,
                    unsure: assistant.today.unsure,
                    notMine: assistant.today.not_mine,
                  })}
                </p>
              )}
            </Panel>

            <Panel icon={MapPin} title={t("where.title")} description={t("where.description")}>
              <Cards
                name="scope"
                value={scope}
                onChange={(value) => setScope(value as "all" | "posts")}
                options={(["all", "posts"] as const).map((value) => ({
                  value,
                  title: t(`where.${value}.title`),
                  about: t(`where.${value}.about`),
                }))}
              />
              {scope === "posts" && (
                <PostPicker
                  accountId={assistant?.account_id ?? accountId}
                  ownId={assistant?.id ?? null}
                  initial={assistant?.media_ids ?? []}
                  owner="assistant"
                  loadPage={loadMedia}
                  loadSelected={loadSelectedMedia}
                />
              )}
              {errors.media_ids && <Alert>{t(`errors.${errors.media_ids}`)}</Alert>}
              {state.conflict && <Conflict conflict={state.conflict} />}
            </Panel>

            <Panel
              icon={MessageSquareText}
              title={t("how.title")}
              description={t("how.description")}
            >
              <Cards
                name="mode"
                value={mode}
                onChange={(value) => setMode(value as AssistantMode)}
                options={MODES.map((value) => ({
                  value,
                  title: t(`how.${value}.title`),
                  about: t(`how.${value}.about`),
                }))}
              />
              <ModelPicker
                connections={connections}
                connectionId={assistant?.connection_id ?? defaults.connectionId}
                model={assistant?.model ?? defaults.model}
                modelMissing={assistant?.model_missing ?? false}
                error={errors.connection_id && t(`errors.${errors.connection_id}`)}
              />
              <FormField name="daily_limit" label={t("limit.label")} description={t("limit.hint")}>
                <Input
                  type="number"
                  min={1}
                  max={LIMITS.dailyLimit}
                  defaultValue={assistant?.daily_limit ?? 200}
                  className="max-w-32"
                />
              </FormField>
            </Panel>

            <Panel
              icon={ScrollText}
              title={t("instruction.title")}
              description={t("instruction.description")}
            >
              <Counted
                name="instruction"
                label={t("instruction.label")}
                defaultValue={assistant?.instruction ?? ""}
                max={LIMITS.instruction}
                rows={6}
              />
            </Panel>

            <Panel
              icon={BookOpen}
              title={t("knowledge.title")}
              description={t("knowledge.description")}
            >
              <Counted
                name="knowledge"
                label={t("knowledge.label")}
                defaultValue={assistant?.knowledge ?? ""}
                max={LIMITS.knowledge}
                rows={12}
              />
            </Panel>
          </fieldset>

          {/* выше экрана колонка листается сама: иначе её низ не увидеть */}
          {canEdit && (
            <div className="grid gap-3 lg:sticky lg:top-4 lg:max-h-[calc(100dvh-2rem)] lg:overflow-y-auto">
              <TryPanel formRef={formRef} mode={mode} />
            </div>
          )}
        </div>

        {/* форма длинная: сохранить можно с любого места, полоса прижата к низу экрана */}
        <div className="sticky bottom-0 z-10 flex flex-wrap items-center justify-end gap-3 border-t bg-background/95 py-3 backdrop-blur">
          {state.failed && (
            <p className="mr-auto text-sm text-destructive" role="alert">
              {t(`errors.${state.failed}`)}
            </p>
          )}
          <Button variant="outline" nativeButton={false} render={<Link href="/assistants" />}>
            {canEdit ? t("cancel") : t("back")}
          </Button>
          {canEdit && (
            <Button type="submit" disabled={pending || archived}>
              {pending ? t("saving") : t("submit")}
            </Button>
          )}
        </div>
      </Page>
    </Form>
  );
}

/** Пауза прямо со страницы: отдельной ручкой, а не вместе с формой. */
function Pause({ assistant }: { assistant: Assistant }) {
  const t = useTranslations("Assistants.form");
  const [, startPause] = useTransition();
  const [enabled, setOptimistic] = useOptimistic(assistant.enabled);
  return (
    <label className="flex items-center gap-2 text-sm">
      <Switch
        checked={enabled}
        onCheckedChange={(next) =>
          startPause(async () => {
            setOptimistic(next);
            await setEnabled(assistant.id, next);
          })
        }
      />
      {enabled ? t("on") : t("off")}
    </label>
  );
}

/** Выбор одного из нескольких карточками: обычные radio с названием и пояснением. */
function Cards({
  name,
  value,
  onChange,
  options,
}: {
  name: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; title: string; about: string }[];
}) {
  return (
    <div className="grid gap-2 md:grid-cols-[repeat(auto-fit,minmax(12rem,1fr))]">
      {options.map((option) => (
        <label
          key={option.value}
          className={cn(
            "grid cursor-pointer gap-1 rounded-lg border p-3 has-focus-visible:ring-3 has-focus-visible:ring-ring/50 has-disabled:cursor-default",
            value === option.value && "border-foreground",
          )}
        >
          <input
            type="radio"
            name={name}
            value={option.value}
            checked={value === option.value}
            onChange={() => onChange(option.value)}
            className="sr-only"
          />
          <span className="text-sm font-medium">{option.title}</span>
          <span className="text-xs text-muted-foreground">{option.about}</span>
        </label>
      ))}
    </div>
  );
}

/** Текст со счётчиком символов: база знаний длинная, предел видно заранее. */
function Counted({
  name,
  label,
  defaultValue,
  max,
  rows,
}: {
  name: string;
  label: string;
  defaultValue: string;
  max: number;
  rows: number;
}) {
  const t = useTranslations("Assistants.form");
  const [value, setValue] = useState(defaultValue);
  return (
    <Field.Root name={name} className="grid gap-2">
      <div className="flex justify-between gap-3">
        <Field.Label render={<Label />}>{label}</Field.Label>
        <span className="text-xs text-muted-foreground tabular-nums">
          {t("chars", { used: value.length, max })}
        </span>
      </div>
      <Field.Control
        value={value}
        onValueChange={(next) => setValue(String(next))}
        maxLength={max}
        render={<textarea className={TEXTAREA} rows={rows} />}
      />
      <Field.Error className="text-sm text-destructive" />
    </Field.Root>
  );
}

function Alert({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-sm text-destructive" role="alert">
      {children}
    </p>
  );
}

function Conflict({ conflict }: { conflict: AssistantConflict }) {
  const t = useTranslations("Assistants.form.conflict");
  return (
    <Alert>
      {t(conflict.kind, {
        name: conflict.assistant.name,
        state: conflict.assistant.enabled ? "on" : "off",
      })}{" "}
      <Link href={`/assistants/${conflict.assistant.id}`} className="underline">
        {t("open")}
      </Link>
    </Alert>
  );
}

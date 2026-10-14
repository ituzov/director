"use client";

import { Field } from "@base-ui/react/field";
import { Form } from "@base-ui/react/form";
import { MessageCircle, MousePointerClick, Package, Send, UserCheck } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { startTransition, useActionState, useEffect, useRef, useState } from "react";

import { FormField } from "@/components/form-field";
import { Page, Panel } from "@/components/page";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Link } from "@/i18n/navigation";
import { type Autoreply, LIMITS, normalizeKeyword } from "@/lib/autoreplies";
import { cn } from "@/lib/utils";

import { type SaveState, saveAutoreply } from "../actions";
import { type PreviewTexts, AutoreplyPreview } from "./autoreply-preview";
import { ChipsInput } from "./chips-input";
import { PostPicker } from "./post-picker";

const INITIAL: SaveState = {};

// как Input, только в несколько строк
const TEXTAREA =
  "min-h-20 w-full rounded-lg border border-input bg-transparent px-2.5 py-2 text-base transition-colors outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20 md:text-sm";

type Props = {
  autoreply: Autoreply | null;
  // аккаунт нового автоответа; у правимого свой, в autoreply.account_id
  accountId: string | null;
  // ник аккаунта для превью; null, если аккаунт не нашёлся
  username: string | null;
};

/** Next прячет страницу при уходе, а не убирает (Activity), и вернувшись по ссылке
 * человек увидел бы недописанное. Новый переход даёт новый bfcacheId и чистую форму;
 * «Назад» в браузере id не меняет, введённое остаётся. */
export function AutoreplyForm(props: Props) {
  const { bfcacheId } = useRouter();
  return <AutoreplyFormFields key={bfcacheId} {...props} />;
}

function AutoreplyFormFields({ autoreply, accountId, username }: Props) {
  const t = useTranslations("AutoreplyForm");
  const [state, action, pending] = useActionState(saveAutoreply, INITIAL);
  const [scope, setScope] = useState(autoreply?.scope ?? "all");
  const [gate, setGate] = useState(autoreply?.follow_gate ?? false);
  const archived = Boolean(autoreply?.archived_at);
  // тексты для превью: поля сообщают их сюда по мере ввода
  const [texts, setTexts] = useState<Omit<PreviewTexts, "gate">>(() => ({
    keyword: autoreply?.keywords[0] ?? "",
    intro: autoreply?.intro_text ?? t("defaults.intro"),
    button: autoreply?.button_text ?? t("defaults.button"),
    reply: autoreply?.reply_text ?? "",
    notFollowing: autoreply?.not_following_text ?? t("defaults.notFollowing"),
    commentReply: autoreply ? (autoreply.comment_replies[0] ?? "") : t("defaults.reply1"),
  }));
  const setText = (key: keyof typeof texts) => (value: string) =>
    setTexts((prev) => ({ ...prev, [key]: value }));
  const formRef = useRef<HTMLFormElement>(null);

  // api вернул ошибку: форма длинная, ведём к самой верхней, иначе её не видно под кнопкой
  useEffect(() => {
    if (!state.errors && !state.conflict && !state.failed) return;
    const first = formRef.current?.querySelector<HTMLElement>(
      '[aria-invalid="true"], [role="alert"]',
    );
    first?.scrollIntoView({ behavior: "smooth", block: "center" });
    // курсор в поле, если это поле: в чипсах это само поле ввода внутри
    (first?.matches("input, textarea") ? first : first?.querySelector("input"))?.focus({
      preventScroll: true,
    });
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
        {autoreply ? (
          <input type="hidden" name="id" value={autoreply.id} />
        ) : (
          <input type="hidden" name="account_id" value={accountId ?? ""} />
        )}
        <input type="hidden" name="enabled" value={String(autoreply?.enabled ?? true)} />

        {archived && (
          <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
            {t("archivedNotice")}
          </p>
        )}

        {/* от lg превью справа и едет вместе с экраном, ниже уходит под форму */}
        <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
          <div className="grid gap-6">
            <Panel
              icon={MousePointerClick}
              title={t("trigger.title")}
              description={t("trigger.description")}
            >
              <FormField
                name="name"
                label={t("name")}
                description={t("nameHint")}
                validate={required}
              >
                <Input defaultValue={autoreply?.name} maxLength={LIMITS.name} autoComplete="off" />
              </FormField>

              <Block
                label={t("keywords")}
                hint={t("keywordsHint")}
                error={errors.keywords && t(`errors.${errors.keywords}`)}
              >
                <ChipsInput
                  name="keywords"
                  onValueChange={(words) => setText("keyword")(words[0] ?? "")}
                  defaultValue={autoreply?.keywords ?? []}
                  placeholder={t("keywordsPlaceholder")}
                  maxItems={LIMITS.keywords}
                  maxLength={100}
                  splitOnComma
                  keyOf={normalizeKeyword}
                  removeLabel={(value) => t("remove", { value })}
                  invalid={Boolean(errors.keywords || state.conflict?.kind === "keyword")}
                />
                {state.conflict?.kind === "keyword" && <Conflict conflict={state.conflict} />}
              </Block>

              <Block
                label={t("scope")}
                hint={t("scopeHint")}
                error={errors.media_ids && t(`errors.${errors.media_ids}`)}
              >
                <Choice
                  name="scope"
                  value={scope}
                  onChange={(value) => setScope(value as "all" | "posts")}
                  options={[
                    { value: "all", label: t("scopeAll") },
                    { value: "posts", label: t("scopePosts") },
                  ]}
                />
                {scope === "posts" && (
                  <PostPicker
                    accountId={autoreply?.account_id ?? accountId}
                    autoreplyId={autoreply?.id ?? null}
                    initial={autoreply?.media_ids ?? []}
                  />
                )}
                {state.conflict?.kind === "post" && <Conflict conflict={state.conflict} />}
              </Block>
            </Panel>

            <Panel icon={Send} title={t("direct.title")} description={t("direct.description")}>
              <Counted
                name="intro_text"
                onValueChange={setText("intro")}
                label={t("introText")}
                hint={t("usernameHint")}
                defaultValue={autoreply?.intro_text ?? t("defaults.intro")}
                max={LIMITS.buttonMessage}
                validate={required}
                multiline
              />
              <Counted
                name="button_text"
                onValueChange={setText("button")}
                label={t("buttonText")}
                defaultValue={autoreply?.button_text ?? t("defaults.button")}
                max={LIMITS.button}
                validate={required}
              />
            </Panel>

            <Panel
              icon={Package}
              title={t("material.title")}
              description={t("material.description")}
            >
              <Counted
                name="reply_text"
                onValueChange={setText("reply")}
                label={t("replyText")}
                hint={t("replyTextHint")}
                defaultValue={autoreply?.reply_text ?? ""}
                max={LIMITS.messageBytes}
                bytes
                validate={required}
                multiline
              />
            </Panel>

            <Panel icon={UserCheck} title={t("gate.title")} description={t("gate.description")}>
              <div className="flex items-center gap-3">
                <Switch
                  id="follow_gate"
                  name="follow_gate"
                  checked={gate}
                  onCheckedChange={setGate}
                />
                <Label htmlFor="follow_gate">{t("gateSwitch")}</Label>
              </div>
              {/* поле живёт и при выключенной проверке: текст не пропадает при переключении */}
              <div className={cn(!gate && "hidden")}>
                <Counted
                  name="not_following_text"
                  onValueChange={setText("notFollowing")}
                  label={t("notFollowingText")}
                  defaultValue={autoreply?.not_following_text ?? t("defaults.notFollowing")}
                  max={LIMITS.buttonMessage}
                  validate={(value) => (gate ? required(value) : null)}
                  multiline
                />
              </div>
            </Panel>

            <Panel
              icon={MessageCircle}
              title={t("comment.title")}
              description={t("comment.description")}
            >
              <CommentReplies
                defaultValue={
                  autoreply
                    ? autoreply.comment_replies
                    : [t("defaults.reply1"), t("defaults.reply2")]
                }
                defaultMode={autoreply?.comment_reply_mode ?? "random"}
                onValueChange={(replies) => setText("commentReply")(replies[0] ?? "")}
                error={errors.comment_replies && t(`errors.${errors.comment_replies}`)}
              />
            </Panel>
          </div>
          {/* выше экрана колонка листается сама: иначе её низ не увидеть */}
          <div className="grid gap-3 lg:sticky lg:top-4 lg:max-h-[calc(100dvh-2rem)] lg:overflow-y-auto">
            <AutoreplyPreview texts={{ ...texts, gate }} account={username} />
          </div>
        </div>

        {/* форма длинная: сохранить можно с любого места, полоса прижата к низу экрана */}
        <div className="sticky bottom-0 z-10 flex flex-wrap items-center justify-end gap-3 border-t bg-background/95 py-3 backdrop-blur">
          {state.failed && (
            <p className="mr-auto text-sm text-destructive" role="alert">
              {t(`errors.${state.failed}`)}
            </p>
          )}
          <Button variant="outline" nativeButton={false} render={<Link href="/autoreplies" />}>
            {t("cancel")}
          </Button>
          <Button type="submit" disabled={pending || archived}>
            {t("submit")}
          </Button>
        </div>
      </Page>
    </Form>
  );
}

/** Поле, которое Base UI не видит (чипсы, выбор): подпись, подсказка и ошибка вручную. */
function Block({
  label,
  hint,
  error,
  children,
}: {
  label: string;
  hint?: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="grid gap-2">
      <Label>{label}</Label>
      {children}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      {error && (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

/** Текст со счётчиком лимита Meta: в знаках или, для обычного сообщения, в байтах. */
function Counted({
  name,
  label,
  hint,
  defaultValue,
  max,
  bytes,
  multiline,
  validate,
  onValueChange,
}: {
  name: string;
  label: string;
  hint?: string;
  defaultValue: string;
  max: number;
  bytes?: boolean;
  multiline?: boolean;
  validate?: (value: unknown) => string | null;
  // текст поменялся: форма показывает его в превью
  onValueChange?: (value: string) => void;
}) {
  const t = useTranslations("AutoreplyForm");
  const [value, setValue] = useState(defaultValue);
  const used = bytes ? new TextEncoder().encode(value).length : value.length;
  const over = used > max;

  return (
    <Field.Root
      name={name}
      validate={(v) => (over ? t("errors.message_too_long") : (validate?.(v) ?? null))}
      className="grid gap-2"
    >
      <Field.Label render={<Label />}>{label}</Field.Label>
      <Field.Control
        value={value}
        onValueChange={(next) => {
          setValue(String(next));
          onValueChange?.(String(next));
        }}
        // в знаках браузер сам не даст превысить; байты считаем сами
        maxLength={bytes ? undefined : max}
        render={multiline ? <textarea className={TEXTAREA} rows={3} /> : <Input />}
      />
      <div className="flex justify-between gap-3 text-xs text-muted-foreground">
        <span>{hint}</span>
        <span className={cn("shrink-0 tabular-nums", over && "text-destructive")}>
          {t(bytes ? "bytes" : "chars", { used, max })}
        </span>
      </div>
      <Field.Error className="text-sm text-destructive" />
    </Field.Root>
  );
}

/** Выбор одного из нескольких: обычные radio, оформленные кнопками. */
function Choice({
  name,
  value,
  onChange,
  options,
}: {
  name: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <div className="inline-flex w-fit flex-wrap rounded-lg border bg-muted/40 p-0.5">
      {options.map((option) => (
        <label
          key={option.value}
          className={cn(
            "cursor-pointer rounded-md px-3 py-1.5 text-sm text-muted-foreground transition-colors has-focus-visible:ring-3 has-focus-visible:ring-ring/50",
            value === option.value && "bg-background text-foreground shadow-sm",
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
          {option.label}
        </label>
      ))}
    </div>
  );
}

function CommentReplies({
  defaultValue,
  defaultMode,
  error,
  onValueChange,
}: {
  defaultValue: string[];
  defaultMode: "random" | "sequence";
  error?: string;
  onValueChange?: (value: string[]) => void;
}) {
  const t = useTranslations("AutoreplyForm");
  const [mode, setMode] = useState(defaultMode);

  return (
    <>
      <Block label={t("commentReplies")} hint={t("commentRepliesHint")} error={error}>
        <ChipsInput
          name="comment_replies"
          defaultValue={defaultValue}
          placeholder={t("commentRepliesPlaceholder")}
          maxItems={LIMITS.commentReplies}
          maxLength={LIMITS.commentReply}
          removeLabel={(value) => t("remove", { value })}
          invalid={Boolean(error)}
          onValueChange={onValueChange}
        />
      </Block>
      <Block label={t("mode")}>
        <Choice
          name="comment_reply_mode"
          value={mode}
          onChange={(value) => setMode(value as "random" | "sequence")}
          options={[
            { value: "random", label: t("modeRandom") },
            { value: "sequence", label: t("modeSequence") },
          ]}
        />
      </Block>
    </>
  );
}

function Conflict({ conflict }: { conflict: NonNullable<SaveState["conflict"]> }) {
  const t = useTranslations("AutoreplyForm");
  return (
    <p className="text-sm text-destructive" role="alert">
      {t.rich(`conflict.${conflict.kind}`, {
        value: conflict.value,
        name: conflict.autoreply.name,
        off: conflict.autoreply.enabled ? "" : t("conflict.disabled"),
        link: (chunks) => (
          <Link href={`/autoreplies/${conflict.autoreply.id}`} className="underline">
            {chunks}
          </Link>
        ),
      })}
    </p>
  );
}

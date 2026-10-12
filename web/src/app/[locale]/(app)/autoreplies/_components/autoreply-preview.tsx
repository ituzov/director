"use client";

import { useTranslations } from "next-intl";

import { Panel } from "@/components/page";
import { cn } from "@/lib/utils";

export type PreviewTexts = {
  keyword: string;
  intro: string;
  button: string;
  reply: string;
  gate: boolean;
  notFollowing: string;
  commentReply: string;
};

/** Как увидит человек: ответ под его комментом и переписка в директе.
 * Ник подставляется как в api (replies.fill): только во вступление и в ответ под комментом. */
export function AutoreplyPreview({
  texts,
  account,
}: {
  texts: PreviewTexts;
  // ник аккаунта автоответа; null, если аккаунт неизвестен
  account: string | null;
}) {
  const t = useTranslations("AutoreplyForm.preview");
  const user = t("sampleUser");
  const me = account ?? t("you");
  const fill = (text: string) => text.replaceAll("{username}", user);

  return (
    <>
      <p className="text-xs text-muted-foreground">{t("label")}</p>
      <Panel size="sm" title={t("underPost")}>
        <Comment
          author={user}
          text={texts.keyword || t("empty.keyword")}
          empty={!texts.keyword}
          meta={t("commentMeta")}
        />
        {texts.commentReply && (
          <div className="pl-10">
            <Comment author={me} text={fill(texts.commentReply)} meta={t("commentMeta")} />
          </div>
        )}
      </Panel>

      <Panel size="sm" title={t("direct")}>
        <Message author={me}>
          <Bubble text={fill(texts.intro)} placeholder={t("empty.intro")} />
          <ChatButton text={texts.button} placeholder={t("empty.button")} />
        </Message>

        <SystemLine text={t("tapped", { user })} />

        {texts.gate && (
          <>
            <Message author={me} label={t("ifNotFollowing")}>
              <Bubble text={texts.notFollowing} placeholder={t("empty.notFollowing")} />
              <ChatButton text={texts.button} placeholder={t("empty.button")} />
            </Message>
            <SystemLine text={t("followed", { user })} />
          </>
        )}

        <Message author={me}>
          <Bubble text={texts.reply} placeholder={t("empty.reply")} />
        </Message>
      </Panel>
    </>
  );
}

/** Кружок с первой буквой: аватарки аккаунта у нас пока нет. */
function Avatar({ name, className }: { name: string; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        "grid shrink-0 place-items-center rounded-full bg-muted text-xs font-medium text-muted-foreground uppercase",
        className,
      )}
    >
      {name.slice(0, 1)}
    </span>
  );
}

function Comment({
  author,
  text,
  meta,
  empty,
}: {
  author: string;
  text: string;
  meta: string;
  empty?: boolean;
}) {
  return (
    <div className="flex gap-2.5">
      <Avatar name={author} className="size-8" />
      <div className="grid min-w-0 gap-0.5 text-sm">
        <p className="break-words">
          <span className="font-semibold">{author}</span>{" "}
          <span className={cn(empty && "text-muted-foreground italic")}>{text}</span>
        </p>
        <p className="text-xs text-muted-foreground">{meta}</p>
      </div>
    </div>
  );
}

/** Сообщения от аккаунта: слева, с маленькой аватаркой у последнего пузыря. */
function Message({
  author,
  label,
  children,
}: {
  author: string;
  label?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="grid gap-1">
      {label && <p className="pl-8 text-xs text-muted-foreground">{label}</p>}
      <div className="flex items-end gap-2">
        <Avatar name={author} className="size-6 text-[0.625rem]" />
        <div className="grid max-w-[80%] gap-1">{children}</div>
      </div>
    </div>
  );
}

function Bubble({ text, placeholder }: { text: string; placeholder: string }) {
  return (
    <p
      className={cn(
        "rounded-[1.25rem] bg-muted px-3.5 py-2 text-sm break-words whitespace-pre-line",
        !text && "text-muted-foreground italic",
      )}
    >
      {text || placeholder}
    </p>
  );
}

/** Кнопка шаблона Meta: отдельная плашка под сообщением. */
function ChatButton({ text, placeholder }: { text: string; placeholder: string }) {
  return (
    <span
      className={cn(
        "rounded-[1.25rem] border bg-background px-3.5 py-2 text-center text-sm font-medium",
        !text && "font-normal text-muted-foreground italic",
      )}
    >
      {text || placeholder}
    </span>
  );
}

/** Что сделал человек: тонкая строка по центру, как служебные строки директа. */
function SystemLine({ text }: { text: string }) {
  return <p className="text-center text-xs text-muted-foreground">{text}</p>;
}

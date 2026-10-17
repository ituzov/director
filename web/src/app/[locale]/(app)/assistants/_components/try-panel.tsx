"use client";

import { FlaskConical } from "lucide-react";
import { useTranslations } from "next-intl";
import { type RefObject, useState, useTransition } from "react";

import { Panel } from "@/components/page";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import type { AssistantMode, TryResult } from "@/lib/assistants";
import { LIMITS } from "@/lib/assistants";

import { tryAssistant } from "../actions";

const TEXTAREA =
  "min-h-20 w-full rounded-lg border border-input bg-transparent px-2.5 py-2 text-base transition-colors outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 md:text-sm";

/** «Проверить коммент»: как ответил бы ассистент с полями, которые сейчас в форме,
 * даже несохранёнными. Ничего не отправляется и в предел не идёт. */
export function TryPanel({
  formRef,
  mode,
}: {
  formRef: RefObject<HTMLFormElement | null>;
  // режим в форме сейчас: какие части ответа показывать
  mode: AssistantMode;
}) {
  const t = useTranslations("Assistants.try");
  const [pending, startTransition] = useTransition();
  const [comment, setComment] = useState("");
  const [result, setResult] = useState<TryResult | null>(null);

  function run() {
    const form = formRef.current;
    if (!form || !comment.trim()) return;
    // вся форма целиком: проверяем то, что владелец видит, а не сохранённое
    const data = new FormData(form);
    startTransition(async () => {
      setResult(await tryAssistant(data).catch(() => ({ error: "server" }) as TryResult));
    });
  }

  return (
    <Panel icon={FlaskConical} title={t("title")} description={t("description")} size="sm">
      <div className="grid gap-2">
        <Label htmlFor="try-comment">{t("comment")}</Label>
        <textarea
          id="try-comment"
          name="try_comment"
          rows={3}
          value={comment}
          maxLength={LIMITS.comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder={t("placeholder")}
          className={TEXTAREA}
        />
      </div>
      <Button
        type="button"
        onClick={run}
        disabled={pending || !comment.trim()}
        className="justify-self-start"
      >
        {pending ? t("thinking") : t("run")}
      </Button>
      {result && <Result result={result} mode={mode} />}
    </Panel>
  );
}

function Result({ result, mode }: { result: TryResult; mode: AssistantMode }) {
  const t = useTranslations("Assistants.try");
  if (result.error || !result.decision) {
    return (
      <p className="border-t pt-3 text-sm text-destructive" role="alert">
        {t("failed", { code: result.error ?? "?" })}
      </p>
    );
  }
  const answered = result.decision === "answer";
  return (
    <div className="grid gap-3 border-t pt-3" role="status">
      <span className={answered ? "text-sm font-medium text-brand" : "text-sm font-medium"}>
        {t(`decision.${result.decision}`)}
      </span>
      {answered && mode !== "direct" && result.comment && (
        <Bubble label={t("inComment")} text={result.comment} />
      )}
      {answered && mode !== "comment" && result.direct && (
        <Bubble label={t("inDirect")} text={result.direct} />
      )}
      {result.source && (
        <p className="text-xs text-muted-foreground">{t("source", { source: result.source })}</p>
      )}
      {result.decision !== "answer" && (
        <p className="text-xs text-muted-foreground">{t(`why.${result.decision}`)}</p>
      )}
    </div>
  );
}

function Bubble({ label, text }: { label: string; text: string }) {
  return (
    <div className="grid gap-1">
      <span className="text-xs text-muted-foreground">{label}</span>
      <p className="rounded-lg bg-muted px-3 py-2 text-sm whitespace-pre-wrap">{text}</p>
    </div>
  );
}

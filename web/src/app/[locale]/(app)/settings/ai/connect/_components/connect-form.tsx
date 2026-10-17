"use client";

import { Form } from "@base-ui/react/form";
import { ArrowUpRight } from "lucide-react";
import { useTranslations } from "next-intl";
import { startTransition, useActionState, useState } from "react";

import { KeyField, NameField } from "@/components/ai-fields";
import { Button } from "@/components/ui/button";
import { Link } from "@/i18n/navigation";
import { PROVIDERS, type ProviderKind } from "@/lib/ai";
import { cn } from "@/lib/utils";

import { connect, type ConnectState } from "../../actions";

const INITIAL: ConnectState = {};

export function ConnectForm() {
  const t = useTranslations("Ai.connect");
  const tProviders = useTranslations("Ai.providers");
  const [state, action, pending] = useActionState(connect, INITIAL);
  const [kind, setKind] = useState<ProviderKind>("anthropic");
  const provider = PROVIDERS.find((p) => p.kind === kind)!;

  if (state.saved) return <Saved result={state.saved} />;

  const fieldErrors = Object.fromEntries(
    Object.entries(state.errors ?? {}).map(([field, code]) => [field, t(`errors.${code}`)]),
  );

  return (
    <Form
      method="post"
      errors={fieldErrors}
      // не action, а onSubmit: при <form action> React 19 сбрасывает поля после ошибки
      onSubmit={(event) => {
        event.preventDefault();
        const data = new FormData(event.currentTarget);
        startTransition(() => action(data));
      }}
      className="grid gap-6"
    >
      <fieldset className="grid gap-2">
        <legend className="mb-2 text-sm font-medium">{t("provider")}</legend>
        <div className="grid gap-2 md:grid-cols-3">
          {PROVIDERS.map((p) => (
            <label
              key={p.kind}
              className={cn(
                "grid cursor-pointer gap-1 rounded-lg border p-3 has-focus-visible:ring-3 has-focus-visible:ring-ring/50",
                kind === p.kind && "border-foreground",
              )}
            >
              <input
                type="radio"
                name="provider"
                value={p.kind}
                checked={kind === p.kind}
                onChange={() => setKind(p.kind)}
                className="sr-only"
              />
              <span className="text-sm font-medium">{tProviders(p.kind)}</span>
              <span className="text-xs text-muted-foreground">{t(`about.${p.kind}`)}</span>
            </label>
          ))}
          {/* следующий по плану: видно, что он будет, выбрать пока нельзя */}
          <div className="grid gap-1 rounded-lg border border-dashed p-3 text-muted-foreground">
            <span className="text-sm font-medium">OpenRouter</span>
            <span className="text-xs">{t("soon")}</span>
          </div>
        </div>
        {state.errors?.provider && (
          <p className="text-sm text-destructive">{t(`errors.${state.errors.provider}`)}</p>
        )}
      </fieldset>
      <NameField label={t("name")} description={t("nameHint")} placeholder={tProviders(kind)} />
      <div className="grid gap-2">
        <KeyField label={t("key")} description={t("keyHint")} />
        <a
          href={provider.keysUrl}
          target="_blank"
          rel="noreferrer"
          className="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground hover:underline"
        >
          {t(`whereKey.${kind}`)}
          <ArrowUpRight className="size-3.5" />
        </a>
      </div>
      <div className="flex flex-wrap items-center gap-4">
        <Button type="submit" disabled={pending}>
          {pending ? t("checking") : t("submit")}
        </Button>
        <Button variant="ghost" nativeButton={false} render={<Link href="/settings/ai" />}>
          {t("cancel")}
        </Button>
      </div>
    </Form>
  );
}

/** Сохранили, но ключ не проверен или с поломкой: что случилось и что делать.
 * Отказ в ключе сюда не доходит: такой api не сохраняет. */
function Saved({ result }: { result: NonNullable<ConnectState["saved"]> }) {
  const t = useTranslations("Ai.connect.saved");
  // у этих свой текст, прочие разовые сбои одним
  const text =
    result === "no_funds" || result === "timeout" || result === "model_missing" ? result : "other";
  const broken = text === "no_funds" || text === "model_missing";

  return (
    <div className="grid gap-4">
      <div role={broken ? "alert" : "status"} className="grid gap-1 text-sm">
        <span className={cn("font-medium", broken && "text-destructive")}>
          {t(`${text}.title`)}
        </span>
        <span className="text-muted-foreground">{t(`${text}.body`)}</span>
      </div>
      <Button className="w-fit" nativeButton={false} render={<Link href="/settings/ai" />}>
        {t("toList")}
      </Button>
    </div>
  );
}

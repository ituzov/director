"use client";

import { Check, Copy } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type Props = { label: string; value: string; hint?: string };

/** Строка, которую человек переносит куда-то ещё: только чтение и кнопка «Скопировать». */
export function CopyField({ label, value, hint }: Props) {
  const t = useTranslations("Common");
  const id = useId();
  const [copied, setCopied] = useState(false);

  async function copy() {
    // буфер обмена доступен только по https и на localhost; не вышло, значит выделит руками
    await navigator.clipboard.writeText(value).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="grid gap-2">
      <Label htmlFor={id}>{label}</Label>
      <div className="flex gap-2">
        <Input
          id={id}
          value={value}
          readOnly
          // клик по полю выделяет всё: удобно копировать и без кнопки
          onFocus={(event) => event.currentTarget.select()}
          className="font-mono"
        />
        {/* высота как у Input: 40px на телефоне, 36px от md */}
        <Button
          type="button"
          variant="outline"
          size="icon"
          className="size-10 md:size-9"
          aria-label={copied ? t("copied") : t("copy")}
          onClick={copy}
        >
          {copied ? <Check /> : <Copy />}
        </Button>
      </div>
      {hint && <p className="text-muted-foreground text-xs">{hint}</p>}
    </div>
  );
}

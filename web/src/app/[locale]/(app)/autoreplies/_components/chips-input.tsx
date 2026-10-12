"use client";

import { X } from "lucide-react";
import { useState } from "react";

import { cn } from "@/lib/utils";

type Props = {
  // имя для FormData: каждая чипса уходит отдельным значением с этим именем
  name: string;
  defaultValue?: string[];
  placeholder?: string;
  maxItems?: number;
  maxLength?: number;
  // запятая тоже отделяет чипсу: для слов да, для фраз-ответов нет
  splitOnComma?: boolean;
  // по чему считать дубли: «Гайд» и «гайд!» для слов одно и то же
  keyOf?: (value: string) => string;
  removeLabel: (value: string) => string;
  invalid?: boolean;
  // чипсы поменялись: форма показывает их в превью
  onValueChange?: (value: string[]) => void;
};

/** Поле-чипсы: пишешь, Enter, появляется плашка с крестиком. Backspace в пустом
 * поле убирает последнюю. Для слов автоответа и вариантов ответа под комментом. */
export function ChipsInput({
  name,
  defaultValue = [],
  placeholder,
  maxItems,
  maxLength,
  splitOnComma = false,
  keyOf = (value) => value,
  removeLabel,
  invalid,
  onValueChange,
}: Props) {
  const [chips, setChips] = useState(defaultValue);
  const [draft, setDraft] = useState("");
  const full = maxItems !== undefined && chips.length >= maxItems;

  // одно место, где чипсы меняются: отсюда же узнаёт и форма
  function update(next: string[]) {
    setChips(next);
    onValueChange?.(next);
  }

  function add(raw: string) {
    const parts = splitOnComma ? raw.split(",") : [raw];
    const next = [...chips];
    for (const part of parts) {
      const value = part.trim();
      if (!value || (maxItems !== undefined && next.length >= maxItems)) continue;
      if (next.some((chip) => keyOf(chip) === keyOf(value))) continue;
      next.push(value);
    }
    update(next);
    setDraft("");
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter" || (splitOnComma && event.key === ",")) {
      // Enter в поле не отправляет всю форму: он добавляет чипсу
      event.preventDefault();
      add(draft);
    } else if (event.key === "Backspace" && !draft && chips.length) {
      update(chips.slice(0, -1));
    }
  }

  return (
    <div
      aria-invalid={invalid || undefined}
      className={cn(
        "flex min-h-10 w-full flex-wrap items-center gap-1.5 rounded-lg border border-input px-2 py-1.5 transition-colors focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/50 aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20 md:min-h-9",
      )}
    >
      {chips.map((chip) => (
        <span
          key={chip}
          className="inline-flex max-w-full items-center gap-1 rounded-md bg-secondary py-0.5 pr-1 pl-2 text-sm text-secondary-foreground"
        >
          <span className="truncate">{chip}</span>
          <button
            type="button"
            onClick={() => update(chips.filter((c) => c !== chip))}
            aria-label={removeLabel(chip)}
            className="rounded-sm p-0.5 text-muted-foreground hover:bg-background hover:text-foreground"
          >
            <X className="size-3.5" />
          </button>
          <input type="hidden" name={name} value={chip} />
        </span>
      ))}
      {!full && (
        <input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={onKeyDown}
          // ушёл из поля, не нажав Enter: не теряем написанное
          onBlur={() => draft.trim() && add(draft)}
          placeholder={chips.length ? undefined : placeholder}
          maxLength={maxLength}
          className="min-w-24 flex-1 bg-transparent py-0.5 text-base outline-none placeholder:text-muted-foreground md:text-sm"
        />
      )}
    </div>
  );
}

"use client";

import { Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import { useActionState } from "react";

import { Button } from "@/components/ui/button";

import { connectInstagram, type ConnectState } from "../actions";

const INITIAL: ConnectState = {};

/** Главная кнопка страницы: уводит на экран Instagram. Ошибка видна прямо под ней. */
export function ConnectButton({ disabled }: { disabled: boolean }) {
  const t = useTranslations("Accounts");
  const [state, action, pending] = useActionState(connectInstagram, INITIAL);

  return (
    <form action={action} className="grid justify-items-end gap-2">
      <Button type="submit" disabled={disabled || pending}>
        <Plus />
        {t("connect")}
      </Button>
      {state.error && (
        <p role="alert" className="max-w-xs text-right text-sm text-destructive">
          {t(`result.${state.error}`)}
        </p>
      )}
    </form>
  );
}

"use client";

import { useTranslations } from "next-intl";
import { useActionState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import { setup, type SetupState } from "../actions";

const INITIAL: SetupState = { email: "" };

export function SetupForm({ token }: { token?: string }) {
  const t = useTranslations("Setup");
  const [state, action, pending] = useActionState(setup, INITIAL);

  return (
    <form action={action} className="grid gap-6">
      <div className="grid gap-4">
        {token ? (
          <input type="hidden" name="token" value={token} />
        ) : (
          <div className="grid gap-2">
            <Label htmlFor="token">{t("token")}</Label>
            <Input id="token" name="token" required autoComplete="off" />
            <p className="text-muted-foreground text-xs">{t("tokenHint")}</p>
          </div>
        )}
        <div className="grid gap-2">
          <Label htmlFor="email">{t("email")}</Label>
          <Input
            id="email"
            name="email"
            type="email"
            required
            autoComplete="email"
            defaultValue={state.email}
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="password">{t("password")}</Label>
          <Input
            id="password"
            name="password"
            type="password"
            required
            minLength={8}
            maxLength={1024}
            autoComplete="new-password"
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="confirm">{t("confirm")}</Label>
          <Input
            id="confirm"
            name="confirm"
            type="password"
            required
            autoComplete="new-password"
          />
        </div>
        {state.error && (
          <p role="alert" className="text-destructive text-sm">
            {t(`errors.${state.error}`)}
          </p>
        )}
      </div>
      <Button type="submit" className="w-full" disabled={pending}>
        {t("submit")}
      </Button>
    </form>
  );
}

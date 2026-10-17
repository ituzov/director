"use client";

import { Form } from "@base-ui/react/form";
import { useTranslations } from "next-intl";
import { useState, useTransition } from "react";

import { KeyField, NameField } from "@/components/ai-fields";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import type { AiConnection } from "@/lib/ai";

import { type Checked, disconnect, editConnection, recheck } from "../actions";

type OnChecked = (checked: Checked & { replaced: boolean }) => void;

type Props = {
  connection: AiConnection;
  // вид, который api не знает: проверить и изменить нельзя, только отключить
  canChange: boolean;
  // итог проверки на карточку: разовый сбой карточку не меняет, а знать о нём надо
  onChecked: OnChecked;
};

export function ConnectionActions({ connection, canChange, onChecked }: Props) {
  const t = useTranslations("Ai.actions");
  const [pending, startTransition] = useTransition();

  return (
    <div className="flex flex-wrap gap-2">
      {canChange && (
        <>
          <Button
            variant="outline"
            disabled={pending}
            onClick={() =>
              startTransition(async () => {
                const result = await recheck(connection.id);
                // удалили в другой вкладке: карточка пропадёт с перерисовкой
                if (!("gone" in result)) onChecked({ ...result, replaced: false });
              })
            }
          >
            {pending ? t("checking") : t("recheck")}
          </Button>
          <EditDialog connection={connection} onChecked={onChecked} />
        </>
      )}
      <DisconnectDialog connection={connection} />
    </div>
  );
}

function EditDialog({ connection, onChecked }: Omit<Props, "canChange">) {
  const t = useTranslations("Ai.actions.edit");
  const tErrors = useTranslations("Ai.connect.errors");
  const [open, setOpen] = useState(false);
  const [pending, startTransition] = useTransition();
  const [errors, setErrors] = useState<Record<string, string>>({});

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        setErrors({});
      }}
    >
      <DialogTrigger render={<Button variant="outline" />}>{t("open")}</DialogTrigger>
      <DialogContent className="sm:max-w-md" closeLabel={t("cancel")}>
        <DialogHeader>
          <DialogTitle className="text-lg">{t("title")}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>
        <Form
          errors={errors}
          onSubmit={(event) => {
            event.preventDefault();
            // FormData, а не объект: ключ не попадёт в лог серверных функций
            const data = new FormData(event.currentTarget);
            data.set("id", connection.id);
            data.set("provider", connection.provider);
            data.set("current_name", connection.name);
            startTransition(async () => {
              const result = await editConnection(data);
              if ("errors" in result) {
                setErrors(
                  Object.fromEntries(
                    Object.entries(result.errors).map(([field, code]) => [field, tErrors(code)]),
                  ),
                );
                return;
              }
              setOpen(false);
              if ("check" in result && result.check && result.stamp) {
                onChecked({ check: result.check, stamp: result.stamp, replaced: true });
              }
            });
          }}
          className="grid gap-4"
        >
          {/* пустое название станет именем провайдера, как при подключении */}
          <NameField label={t("name")} defaultValue={connection.name} />
          <KeyField
            label={t("key")}
            description={t("keyHint", { hint: connection.key_hint })}
            optional
          />
          <DialogFooter>
            <DialogClose render={<Button variant="outline" />}>{t("cancel")}</DialogClose>
            <Button type="submit" disabled={pending}>
              {pending ? t("saving") : t("save")}
            </Button>
          </DialogFooter>
        </Form>
      </DialogContent>
    </Dialog>
  );
}

function DisconnectDialog({ connection }: { connection: AiConnection }) {
  const t = useTranslations("Ai.actions.disconnect");
  const [pending, startTransition] = useTransition();

  return (
    <Dialog>
      <DialogTrigger render={<Button variant="ghost" />}>{t("open")}</DialogTrigger>
      <DialogContent className="sm:max-w-md" closeLabel={t("cancel")}>
        <DialogHeader>
          <DialogTitle className="text-lg">{t("title", { name: connection.name })}</DialogTitle>
          <DialogDescription>
            {connection.tasks.length > 0 ? t("withTasks") : t("withoutTasks")}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <DialogClose render={<Button variant="outline" />}>{t("cancel")}</DialogClose>
          <Button
            variant="destructive"
            disabled={pending}
            onClick={() => startTransition(() => disconnect(connection.id))}
          >
            {t("confirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

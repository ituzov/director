"use client";

import { Circle, CircleCheck, CircleX, LoaderCircle } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import type { UpdatePoll } from "@/lib/updates";
import { cn } from "@/lib/utils";

// шаги install.sh update по порядку: первое слово строки на доске
const STEPS = ["download", "pull", "backup", "switch", "start", "waiting", "cleanup"] as const;
type Step = (typeof STEPS)[number];

const POLL_MS = 2000;
// столько без единого изменения на доске, и честно говорим, что что-то не так
const STALL_MS = 10 * 60 * 1000;
// «Готово» успевают прочитать до перезагрузки
const RELOAD_MS = 1500;

type View =
  | { kind: "progress"; step: Step | null }
  | { kind: "stuck" }
  | { kind: "stalled" }
  | { kind: "done" }
  | { kind: "failed"; reason: "error" | "rolledBack" | "rollbackFailed"; log: string[] };

/**
 * Ход обновления до target по доске хоста. Опрос раз в 2 секунды через
 * /api/update/status. Пока api и админка перезапускаются, ответа нет: это шаг
 * «Запускаю», а не ошибка. Готово, только когда ответил сервер новой версии.
 */
export function UpdateProgress({
  target,
  requestedAt,
  onFinish,
}: {
  target: string;
  // время просьбы по часам сервера: итог на доске раньше него остался от прошлого раза
  requestedAt: string | null;
  onFinish: () => void;
}) {
  const t = useTranslations("App.updates.progress");
  const [view, setView] = useState<View>({ kind: "progress", step: null });

  useEffect(() => {
    let last = "";
    let changedAt = Date.now();
    let stopped = false;
    const since = requestedAt ? Date.parse(requestedAt) : 0;

    const finish = (next: View) => {
      stopped = true;
      setView(next);
      onFinish();
    };

    const tick = async () => {
      const poll = await fetch("/api/update/status", { cache: "no-store" })
        .then((r) => r.json() as Promise<UpdatePoll>)
        // сервер админки перезапускается и не отвечает совсем
        .catch((): UpdatePoll => ({ phase: "restarting", version: "" }));
      if (stopped) return;

      const mark = poll.phase === "restarting" ? "restarting" : `${poll.phase} ${poll.step}`;
      if (mark !== last) [last, changedAt] = [mark, Date.now()];
      else if (Date.now() - changedAt > STALL_MS) return finish({ kind: "stalled" });

      if (poll.phase === "restarting") return setView({ kind: "progress", step: "start" });
      if (poll.phase === "stuck") return setView({ kind: "stuck" });
      // итог с доски раньше нашей просьбы остался от прошлого обновления: ждём свежий
      const fresh = poll.at !== null && Date.parse(poll.at) >= since;
      if (poll.phase === "done" && fresh && poll.version === target) {
        finish({ kind: "done" });
        setTimeout(() => window.location.reload(), RELOAD_MS);
        return;
      }
      if (poll.phase === "failed" && fresh) {
        const step = poll.step ?? "";
        const reason = step.startsWith("error")
          ? "error"
          : step.includes("did not start")
            ? "rollbackFailed"
            : "rolledBack";
        return finish({ kind: "failed", reason, log: poll.log });
      }
      if (poll.phase === "running") {
        const word = poll.step?.split(" ")[0] ?? "";
        const step = STEPS.includes(word as Step) ? (word as Step) : null;
        setView((v) => (v.kind === "progress" && step === null ? v : { kind: "progress", step }));
      }
    };

    void tick();
    const timer = setInterval(() => void tick(), POLL_MS);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [target, requestedAt, onFinish]);

  if (view.kind === "done") {
    return <Result ok text={t("done", { version: target })} />;
  }
  if (view.kind === "failed") {
    return (
      <div className="grid gap-3">
        <Result text={t(`failed.${view.reason}`)} />
        {view.log.length > 0 && (
          <details className="rounded-lg bg-muted px-3 py-2">
            <summary className="cursor-pointer">{t("log")}</summary>
            <pre className="mt-2 max-h-48 overflow-auto text-xs whitespace-pre-wrap">
              {view.log.join("\n")}
            </pre>
          </details>
        )}
      </div>
    );
  }
  if (view.kind === "stuck" || view.kind === "stalled") {
    return (
      <div className="grid gap-2">
        <Result text={t(view.kind)} />
        <code className="rounded-lg bg-muted px-3 py-2 text-xs">
          {view.kind === "stuck"
            ? `sudo /opt/director/install.sh update ${target}`
            : "cat /opt/director/run/update.log"}
        </code>
      </div>
    );
  }

  const current = view.step ? STEPS.indexOf(view.step) : 0;
  return (
    <ol className="grid gap-2" aria-live="polite">
      {STEPS.map((step, i) => (
        <li
          key={step}
          className={cn("flex items-center gap-2", i > current && "text-muted-foreground")}
        >
          {i < current ? (
            <CircleCheck className="size-4 shrink-0 text-brand" />
          ) : i === current ? (
            <LoaderCircle className="size-4 shrink-0 animate-spin" />
          ) : (
            <Circle className="size-4 shrink-0" />
          )}
          {t(`steps.${step}`)}
        </li>
      ))}
    </ol>
  );
}

function Result({ ok = false, text }: { ok?: boolean; text: string }) {
  return (
    <p className="flex items-start gap-2">
      {ok ? (
        <CircleCheck className="mt-0.5 size-4 shrink-0 text-brand" />
      ) : (
        <CircleX className="mt-0.5 size-4 shrink-0 text-destructive" />
      )}
      {text}
    </p>
  );
}

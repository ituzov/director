import { useFormatter, useTranslations } from "next-intl";

import { isFailure, type Step } from "@/lib/inbox";
import { cn } from "@/lib/utils";

import { failureText, longTime, shortTime, stepText } from "./labels";

/** Что было с комментом после автоответа, по шагам. В DOM всегда: на него
 * указывает aria-controls кнопки, закрытый просто скрыт. className задаёт колонки:
 * в строке ленты сетка строки (subgrid), в карточке своя. */
export function Steps({
  id,
  open,
  steps,
  now,
  className,
}: {
  id: string;
  open: boolean;
  steps: Step[];
  now: number;
  className: string;
}) {
  const t = useTranslations("Inbox");
  const format = useFormatter();

  return (
    <ol id={id} hidden={!open} className={cn("grid gap-y-1.5", className)}>
      {steps.map((step, i) => {
        const at = new Date(step.at);
        const failure = isFailure(step.step);
        return (
          <li key={i} className="col-span-full grid grid-cols-subgrid">
            <time
              dateTime={step.at}
              title={longTime(at, format)}
              className="text-muted-foreground tabular-nums"
            >
              {shortTime(at, now, format)}
            </time>
            <div className={cn("col-[2/-1]", failure && "text-destructive")}>
              <p>{stepText(step, t)}</p>
              {failure && <p className="text-muted-foreground">{failureText(step, t)}</p>}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

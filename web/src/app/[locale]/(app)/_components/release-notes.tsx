import { Fragment } from "react";

/**
 * Заметки к версии из versions.json. Пишутся простым markdown, понимаем три
 * вещи: `## Заголовок`, пункты `- …` и `код` в обратных кавычках. Остальное
 * обычный текст: HTML не разбираем, поэтому через файл на сайте чужую
 * разметку на страницу не подсунуть.
 */
export function ReleaseNotes({ text }: { text: string }) {
  const blocks: React.ReactNode[] = [];
  let items: string[] = [];
  let paragraph: string[] = [];

  const flush = () => {
    if (items.length) {
      blocks.push(
        <ul key={blocks.length} className="grid list-disc gap-1 pl-5">
          {items.map((item, i) => (
            <li key={i}>
              <Inline text={item} />
            </li>
          ))}
        </ul>,
      );
      items = [];
    }
    if (paragraph.length) {
      blocks.push(
        <p key={blocks.length} className="whitespace-pre-line">
          <Inline text={paragraph.join("\n")} />
        </p>,
      );
      paragraph = [];
    }
  };

  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (line.startsWith("## ")) {
      flush();
      blocks.push(
        <h4 key={blocks.length} className="font-medium text-foreground">
          {line.slice(3)}
        </h4>,
      );
    } else if (line.startsWith("- ")) {
      if (paragraph.length) flush();
      items.push(line.slice(2));
    } else if (line === "") {
      flush();
    } else {
      if (items.length) flush();
      paragraph.push(line);
    }
  }
  flush();

  return <div className="grid gap-2 text-muted-foreground">{blocks}</div>;
}

/** `код` моноширинным, остальное как есть. */
function Inline({ text }: { text: string }) {
  return text.split(/(`[^`]+`)/).map((part, i) =>
    part.startsWith("`") && part.endsWith("`") && part.length > 1 ? (
      <code key={i} className="rounded bg-muted px-1 py-0.5 font-mono text-xs text-foreground">
        {part.slice(1, -1)}
      </code>
    ) : (
      <Fragment key={i}>{part}</Fragment>
    ),
  );
}

import { useState, useTransition } from "react";

import type { History } from "@/lib/inbox";

type Page<T> = { items: T[]; next: string | null };

/** Список по страницам: строки, их история и закладка следующей страницы. load
 * догружает страницу старше закладки. */
export function useFeed<T, H extends Record<string, unknown[]> = History>(
  initial: Page<T>,
  initialHistory: H,
  // история есть у выдач и ответов ассистента; у «Всех событий» её нет: там только разбор
  load: (before: string) => Promise<{ page: Page<T>; history?: H }>,
) {
  const [items, setItems] = useState(initial.items);
  const [history, setHistory] = useState(initialHistory);
  const [next, setNext] = useState(initial.next);
  const [failed, setFailed] = useState(false);
  const [pending, startTransition] = useTransition();

  function more() {
    if (!next) return;
    setFailed(false);
    startTransition(async () => {
      try {
        const { page, history: more } = await load(next);
        setItems((prev) => [...prev, ...page.items]);
        // коммент лежит на одной странице: истории порций не пересекаются
        if (more) setHistory((prev) => ({ ...prev, ...more }));
        setNext(page.next);
      } catch {
        setFailed(true);
      }
    });
  }

  return { items, history, next, failed, pending, more };
}

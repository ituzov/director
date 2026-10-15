import { useState, useTransition } from "react";

import type { History, InboxPage } from "@/lib/inbox";

import { loadInbox } from "../actions";

/** Лента по страницам: строки, их история и закладка следующей страницы. */
export function useFeed(accountId: string, initial: InboxPage, initialHistory: History) {
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
        const { page, history: more } = await loadInbox(accountId, next);
        setItems((prev) => [...prev, ...page.items]);
        // коммент лежит на одной странице: истории порций не пересекаются
        setHistory((prev) => ({ ...prev, ...more }));
        setNext(page.next);
      } catch {
        setFailed(true);
      }
    });
  }

  return { items, history, next, failed, pending, more };
}

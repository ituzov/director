import { useSyncExternalStore } from "react";

const subscribe = () => () => {};

/** true только в браузере после гидрации. На сервере и в первом проходе браузера false,
 * поэтому разметка совпадает: то, что зависит от браузера (пояс, язык), рисуем после. */
export function useInBrowser() {
  return useSyncExternalStore(
    subscribe,
    () => true,
    () => false,
  );
}

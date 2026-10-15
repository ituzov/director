import { useTranslations } from "next-intl";

import { type StageCounts, type Tab, TAB_KEYS, tabCount } from "@/lib/deliveries";

import { CountTabs } from "./count-tabs";

/** Вкладки этапов «Выдач»: кто сейчас на каком шаге. */
export function DeliveryTabs({ tab, counts }: { tab: Tab; counts: StageCounts }) {
  const t = useTranslations("Inbox.tabs");
  return (
    <CountTabs
      label={t("label")}
      tabs={TAB_KEYS.map((key) => ({
        key,
        href: key === "all" ? "/journal" : `/journal?tab=${key}`,
        label: t(key),
        count: tabCount(key, counts),
        current: tab === key,
      }))}
    />
  );
}

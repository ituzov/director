import { useTranslations } from "next-intl";

import { RESULT_TABS, type ResultCounts, resultCount, type ResultTab } from "@/lib/events";

import { CountTabs } from "./count-tabs";

/** Вкладки итога «Всех событий»: что взяли, что нет и почему. */
export function EventsTabs({ tab, counts }: { tab: ResultTab; counts: ResultCounts }) {
  const t = useTranslations("Inbox.results");
  return (
    <CountTabs
      label={t("label")}
      tabs={RESULT_TABS.map((key) => ({
        key,
        href: key === "all" ? "/journal?view=all" : `/journal?view=all&result=${key}`,
        label: t(key),
        count: resultCount(key, counts),
        current: tab === key,
      }))}
    />
  );
}

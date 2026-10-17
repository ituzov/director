import { useTranslations } from "next-intl";

import { ASSISTANT_TABS, type AssistantCounts, type AssistantTab } from "@/lib/assistant-replies";

import { CountTabs } from "./count-tabs";

/** Вкладки «Ассистента»: что он сделал с комментами. */
export function AssistantTabs({ tab, counts }: { tab: AssistantTab; counts: AssistantCounts }) {
  const t = useTranslations("Inbox.assistant.tabs");
  return (
    <CountTabs
      label={t("label")}
      tabs={ASSISTANT_TABS.map((key) => ({
        key,
        href: key === "all" ? "/journal?view=assistant" : `/journal?view=assistant&tab=${key}`,
        label: t(key),
        count: counts[key] ?? 0,
        current: tab === key,
      }))}
    />
  );
}

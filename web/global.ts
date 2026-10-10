// Строгие типы next-intl: t() знает ключи, useLocale() знает языки.
import en from "./messages/en.json";
import ru from "./messages/ru.json";
import { routing } from "@/i18n/routing";

// эталон ru: в en не хватит ключа, сломается сборка, а не экран
en satisfies typeof ru;

declare module "next-intl" {
  interface AppConfig {
    Locale: (typeof routing.locales)[number];
    Messages: typeof ru;
  }
}

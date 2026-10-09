import { defineRouting } from "next-intl/routing";

export const routing = defineRouting({
  locales: ["ru", "en"],
  defaultLocale: "ru",
  // Язык в cookie, адреса без /ru и /en. Внутри proxy переписывает
  // запрос в папку [locale], поэтому страницы остаются статическими.
  localePrefix: "never",
});

import { defineRouting } from "next-intl/routing";

export const routing = defineRouting({
  locales: ["ru", "en"],
  defaultLocale: "ru",
  // Язык в cookie, адреса без /ru и /en. Внутри proxy переписывает
  // запрос в папку [locale], поэтому страницы остаются статическими.
  localePrefix: "never",
  // По умолчанию cookie языка сессионная и умирает с браузером.
  // Без префикса в адресе выбор помнит только она, поэтому храним год
  localeCookie: { maxAge: 60 * 60 * 24 * 365 },
});

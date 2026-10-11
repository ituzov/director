/** @type {import("prettier").Config & import("prettier-plugin-tailwindcss").PluginOptions} */
const config = {
  printWidth: 100,
  plugins: ["prettier-plugin-tailwindcss"],
  // Tailwind v4: классы сортируются по нашему globals.css, с нашими токенами
  tailwindStylesheet: "./src/app/globals.css",
  // классы внутри cn() и cva() тоже сортируются
  tailwindFunctions: ["cn", "cva"],
};

export default config;

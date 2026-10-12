import createMiddleware from "next-intl/middleware";
import { type NextRequest, NextResponse } from "next/server";

import { routing } from "@/i18n/routing";
import { SESSION_COOKIE } from "@/lib/session-cookie";

const handleI18nRouting = createMiddleware(routing);

// страницы, куда пускаем без сессии
const PUBLIC = ["/login", "/setup", "/privacy"];

export default function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const isPublic = PUBLIC.some((p) => pathname === p || pathname.startsWith(`${p}/`));

  // только оптимистичная проверка: есть ли cookie. Жива ли сессия, решает api на странице.
  // Обратного редиректа (с /login при cookie) здесь нет: протухшая cookie дала бы петлю
  if (!isPublic && !request.cookies.has(SESSION_COOKIE)) {
    return NextResponse.redirect(new URL("/login", request.url));
  }
  return handleI18nRouting(request);
}

export const config = {
  // icon и apple-icon: картинки иконок без расширения в адресе, язык им не нужен
  matcher: "/((?!api|_next|_vercel|icon|apple-icon|.*\\..*).*)",
};

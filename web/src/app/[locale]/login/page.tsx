import { useTranslations } from "next-intl";
import { redirect } from "next/navigation";
import { connection } from "next/server";

import { AuthShell } from "@/components/auth-shell";
import { apiFetch } from "@/lib/api";

import { LoginForm } from "./_components/login-form";

// без стриминга: сначала спрашиваем api, потом отвечаем. Иначе оболочка входа
// успевает показаться, и переход на /setup выглядит миганием
export const instant = false;

export default function LoginPage() {
  const t = useTranslations("Login");

  return (
    <AuthShell title={t("title")} description={t("description")}>
      <Login />
    </AuthShell>
  );
}

async function Login() {
  // данных запроса тут нет, поэтому пререндер останавливаем явно: дальше ходим в api
  await connection();

  // свежая установка: входить ещё некому, сначала регистрация
  const { needed } = await apiFetch<{ needed: boolean }>("/setup");
  if (needed) redirect("/setup");

  return <LoginForm />;
}

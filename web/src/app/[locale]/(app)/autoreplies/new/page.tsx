import { Suspense } from "react";

import { getCurrentAccount } from "@/lib/current-account";

import { AutoreplyForm } from "../_components/autoreply-form";

/** Новый автоответ выбранного в меню аккаунта: аккаунт берёт действие сохранения. */
export default function NewAutoreplyPage() {
  return (
    <Suspense>
      <New />
    </Suspense>
  );
}

/** Ник выбранного аккаунта для превью. Читает cookie: только внутри Suspense. */
async function New() {
  const account = await getCurrentAccount();
  return <AutoreplyForm autoreply={null} username={account?.username ?? null} />;
}

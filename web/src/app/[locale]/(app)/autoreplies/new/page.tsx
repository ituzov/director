import { Suspense } from "react";

import { getCurrentAccount } from "@/lib/current-account";

import { AutoreplyForm } from "../_components/autoreply-form";

/** Новый автоответ выбранного в меню аккаунта. Аккаунт уходит в форму скрытым
 * полем: сохранится туда, для какого открыли, что бы ни выбрали в другой вкладке. */
export default function NewAutoreplyPage() {
  return (
    <Suspense>
      <New />
    </Suspense>
  );
}

/** Выбранный аккаунт: id в форму, ник для превью. Читает cookie: только внутри Suspense. */
async function New() {
  const account = await getCurrentAccount();
  return (
    <AutoreplyForm
      autoreply={null}
      accountId={account?.id ?? null}
      username={account?.username ?? null}
    />
  );
}

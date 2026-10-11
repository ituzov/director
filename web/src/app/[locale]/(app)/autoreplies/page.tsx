import { MessageSquareReply, Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import { Suspense } from "react";

import { Page, Panel } from "@/components/page";
import { Button } from "@/components/ui/button";
import { Link } from "@/i18n/navigation";
import { apiFetch } from "@/lib/api";
import type { Autoreply } from "@/lib/autoreplies";
import { getCurrentAccount } from "@/lib/current-account";
import { getToken } from "@/lib/session";

import { ArchiveTabs } from "./_components/archive-tabs";
import { AutoreplyList, AutoreplyListSkeleton } from "./_components/autoreply-list";

type Props = { searchParams: Promise<{ archived?: string }> };

export default function AutorepliesPage({ searchParams }: Props) {
  const t = useTranslations("Autoreplies");

  return (
    // список карточек: на широком экране больше карточек в ряд, а не шире строки
    <Page width="wide">
      <Panel
        icon={MessageSquareReply}
        title={t("title")}
        description={t("description")}
        actions={
          // ссылка в виде кнопки: nativeButton={false}, иначе Base UI ждёт настоящий <button>
          <Button nativeButton={false} render={<Link href="/autoreplies/new" />}>
            <Plus />
            {t("create")}
          </Button>
        }
      >
        <Suspense fallback={<AutoreplyListSkeleton />}>
          <Autoreplies searchParams={searchParams} />
        </Suspense>
      </Panel>
    </Page>
  );
}

/** Автоответы аккаунта из переключателя. Читает cookie и api: только внутри Suspense. */
async function Autoreplies({ searchParams }: Props) {
  const archived = (await searchParams).archived === "1";
  const account = await getCurrentAccount();
  if (!account) return <NoAccount />;

  const query = new URLSearchParams({ account_id: account.id, archived: String(archived) });
  const autoreplies = await apiFetch<Autoreply[]>(`/autoreplies?${query}`, {
    token: await getToken(),
  });
  return (
    <>
      <ArchiveTabs archived={archived} />
      <AutoreplyList autoreplies={autoreplies} archived={archived} />
    </>
  );
}

function NoAccount() {
  const t = useTranslations("Autoreplies");
  return (
    <p className="text-sm text-muted-foreground">
      {t.rich("noAccount", {
        link: (chunks) => (
          <Link href="/accounts" className="text-foreground underline">
            {chunks}
          </Link>
        ),
      })}
    </p>
  );
}

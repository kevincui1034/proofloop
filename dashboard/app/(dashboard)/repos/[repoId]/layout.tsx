import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { auth } from "@/auth";
import { getRepo } from "@/lib/queries/traces";
import { RepoTabs } from "@/components/RepoTabs";

export default async function RepoLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ repoId: string }>;
}) {
  const session = await auth();
  if (!session?.user) redirect("/login");
  const { repoId } = await params;
  const repo = await getRepo(session.user.id, repoId);
  if (!repo) notFound();

  return (
    <div>
      <div className="flex items-baseline gap-3">
        <Link href="/repos" className="text-sm text-faint hover:text-ink">
          repos /
        </Link>
        <h1 className="font-mono text-2xl text-ink">
          {repo.displayName ?? repo.repoSlug}
        </h1>
      </div>
      <RepoTabs repoId={repoId} />
      <div className="mt-6">{children}</div>
    </div>
  );
}

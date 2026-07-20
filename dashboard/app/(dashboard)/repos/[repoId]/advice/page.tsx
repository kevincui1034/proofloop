import Link from "next/link";
import { notFound } from "next/navigation";

import { auth } from "@/auth";
import {
  ClassChip,
  DeliveryBadge,
  EvidenceText,
  LabelBadge,
  timeAgo,
} from "@/components/badges";
import { adviceFeed } from "@/lib/queries/advice";
import { getRepo } from "@/lib/queries/traces";

export default async function AdvicePage({
  params,
}: {
  params: Promise<{ repoId: string }>;
}) {
  const session = await auth();
  const { repoId } = await params;
  const repo = await getRepo(session!.user.id, repoId);
  if (!repo) notFound();
  const events = await adviceFeed(repo.id);

  if (events.length === 0) {
    return (
      <p className="text-faint">
        Nothing yet — the judge speaks when a gate blocks or an advisory
        finding fires.
      </p>
    );
  }

  return (
    <ol className="relative flex flex-col gap-4 border-l border-line pl-6">
      {events.map((event, i) => (
        <li key={i} className="relative">
          <span
            className={`absolute -left-[1.85rem] top-1.5 h-2.5 w-2.5 rounded-full ${
              event.type === "deny" ? "bg-verdict-red" : "bg-amber"
            }`}
          />
          <div className="rounded-lg border border-line bg-surface-2 p-4">
            {event.type === "deny" ? (
              <>
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <span className="font-medium text-verdict-red">BLOCKED</span>
                  <Link
                    href={`/repos/${repoId}/traces/${event.recordId}`}
                    className="font-mono text-ink hover:underline"
                  >
                    {event.recordId}
                  </Link>
                  {event.failureClasses.map((cls) => (
                    <ClassChip key={cls} name={cls} />
                  ))}
                  {event.recalledFrom && (
                    <span className="text-amber-ink">
                      ↩ {event.recalledFrom}
                    </span>
                  )}
                  <span className="ml-auto text-faint">
                    {timeAgo(event.createdAt)}
                  </span>
                </div>
                <p className="mt-2 text-sm text-body">
                  <EvidenceText text={event.diagnosis} />
                </p>
                {event.resolvedBy ? (
                  <p className="mt-2 text-xs text-verdict-green">
                    ✓ advice followed — resolved by{" "}
                    <Link
                      href={`/repos/${repoId}/traces/${event.resolvedBy}`}
                      className="font-mono hover:underline"
                    >
                      {event.resolvedBy}
                    </Link>
                  </p>
                ) : (
                  <p className="mt-2 text-xs text-faint">not yet resolved</p>
                )}
              </>
            ) : (
              <>
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <span className="font-medium text-amber-ink">ADVISORY</span>
                  <Link
                    href={`/repos/${repoId}/traces/${event.recordId}`}
                    className="font-mono text-ink hover:underline"
                  >
                    {event.recordId}#{event.idx}
                  </Link>
                  {event.tier !== null && (
                    <span className="text-faint">tier {event.tier}</span>
                  )}
                  <DeliveryBadge delivery={event.delivery} />
                  <LabelBadge label={event.label} />
                  {event.retraction && (
                    <span className="text-verdict-red">
                      retraction {event.retraction}
                    </span>
                  )}
                  <span className="ml-auto text-faint">
                    {timeAgo(event.createdAt)}
                  </span>
                </div>
                <p className="mt-2 text-sm text-body">
                  <EvidenceText text={event.concern} />
                </p>
                {event.target && (
                  <p className="mt-1 font-mono text-xs text-amber-ink">
                    {event.target}
                  </p>
                )}
              </>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}

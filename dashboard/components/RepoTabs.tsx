"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { slug: "", label: "Overview" },
  { slug: "traces", label: "Traces" },
  { slug: "advice", label: "Judge advice" },
  { slug: "graduation", label: "Graduation" },
  { slug: "memory", label: "Memory" },
] as const;

export function RepoTabs({ repoId }: { repoId: string }) {
  const pathname = usePathname();
  const base = `/repos/${repoId}`;
  return (
    <nav className="mt-4 flex gap-1 border-b border-line">
      {TABS.map((tab) => {
        const href = tab.slug ? `${base}/${tab.slug}` : base;
        const active = tab.slug
          ? pathname.startsWith(`${base}/${tab.slug}`)
          : pathname === base;
        return (
          <Link
            key={tab.slug}
            href={href}
            className={
              active
                ? "border-b-2 border-amber px-4 py-2 text-sm text-ink"
                : "px-4 py-2 text-sm text-faint hover:text-body"
            }
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}

import { GITHUB_URL, GitHubIcon, GateGlyph } from "./brand";

/**
 * Fixed chrome that lives in BOTH worlds — every color is a semantic token,
 * so the S4 root flip restyles it behind the opaque flood.
 */
export default function Nav() {
  return (
    <header className="fixed inset-x-0 top-0 z-50 border-b border-line/70 bg-surface/85 backdrop-blur-md">
      <nav className="mx-auto flex h-[52px] max-w-6xl items-center justify-between px-5">
        <a
          href="#top"
          className="flex items-center gap-2 font-mono text-[15px] font-semibold tracking-tight text-ink"
        >
          <GateGlyph className="h-[17px] w-[17px]" />
          proofjury
        </a>
        <div className="flex items-center gap-2 sm:gap-4">
          <a
            href={GITHUB_URL}
            target="_blank"
            rel="noopener noreferrer"
            aria-label="Proofjury on GitHub"
            className="flex items-center gap-1.5 rounded-md px-2 py-1.5 text-sm text-body transition-colors hover:text-ink"
          >
            <GitHubIcon />
            <span className="hidden sm:inline">GitHub</span>
          </a>
          <a
            href="#early-access"
            className="rounded-md bg-amber px-3.5 py-1.5 text-sm font-semibold text-[#171006] transition-[filter] hover:brightness-110"
          >
            Get early access
          </a>
        </div>
      </nav>
    </header>
  );
}

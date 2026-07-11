import ExperienceRoot from "@/components/experience/ExperienceRoot";
import GLStage from "@/components/gl/GLStage";
import Nav from "@/components/ui/Nav";
import S1Hero from "@/components/scenes/S1Hero";
import S2Journey from "@/components/scenes/S2Journey";
import S3Mistakes from "@/components/scenes/S3Mistakes";
import S4Verdict from "@/components/scenes/S4Verdict";
import S5ProofRecord from "@/components/scenes/S5ProofRecord";
import S6Memory from "@/components/scenes/S6Memory";
import S7Neutrality from "@/components/scenes/S7Neutrality";
import S8Cta from "@/components/scenes/S8Cta";

export default function Home() {
  return (
    <>
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[60] focus:rounded-md focus:bg-amber focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:text-[#171006]"
      >
        Skip to content
      </a>
      <Nav />
      <ExperienceRoot />
      <main id="main" className="min-w-0">
        <div id="top" />

        {/* CHAPTER I — night. Statically scoped: this chapter stays dark even
            after the S4 flood flips the root world for the global chrome. */}
        <div data-world="night" className="relative bg-surface text-body">
          {/* viewport-tracking atmosphere layer: CSS beam now, WebGL canvas
              mounts here in the GL phase. Sticky + negative margin keeps it
              behind the night scenes without position:fixed. */}
          <div
            data-gl="mount"
            aria-hidden="true"
            className="pointer-events-none sticky top-0 z-0 -mb-[100svh] h-svh"
          >
            <div data-gl="fallback" className="beam-fallback absolute inset-0" />
            <GLStage />
          </div>
          <S1Hero />
          <S2Journey />
          <S3Mistakes />
          <S4Verdict />
        </div>

        {/* CHAPTER II — paper. The proof-record world. No grain overlay here:
            the S4 flood is flat --surface, and any texture difference reads
            as a seam at the handoff. */}
        <div data-world="paper" className="relative bg-surface text-body">
          <S5ProofRecord />
          <S6Memory />
          <S7Neutrality />
          <S8Cta />
        </div>
      </main>
    </>
  );
}

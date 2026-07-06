import Nav from "@/components/Nav";
import Hero from "@/components/sections/Hero";
import Problem from "@/components/sections/Problem";
import Interception from "@/components/sections/Interception";
import Proof from "@/components/sections/Proof";
import Memory from "@/components/sections/Memory";
import Neutrality from "@/components/sections/Neutrality";
import CTA from "@/components/sections/CTA";

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
      <main id="main" className="min-w-0">
        <div id="top" />
        <Hero />
        <Problem />
        <Interception />
        <Proof />
        <Memory />
        <Neutrality />
        <CTA />
      </main>
    </>
  );
}

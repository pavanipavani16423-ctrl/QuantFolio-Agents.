import type { Metadata } from "next";
import { SystemView } from "@/components/system-view";
import { Accent, Eyebrow } from "@/components/ui";

export const metadata: Metadata = { title: "How it works" };

export default function HowItWorks() {
  return (
    <div className="hero-glow">
      <div className="mx-auto max-w-6xl px-4 pt-16 pb-24 sm:px-6">
        <div className="flex flex-col items-center text-center">
          <Eyebrow>Under the hood</Eyebrow>
          <h1 className="display mt-6 text-5xl font-semibold sm:text-7xl">
            How the team <Accent>works</Accent>.
          </h1>
          <p className="mt-6 max-w-2xl text-lg text-muted-foreground">
            A plain explanation first, then the real architecture, read live from the running system.
          </p>
        </div>
        <SystemView />
      </div>
    </div>
  );
}

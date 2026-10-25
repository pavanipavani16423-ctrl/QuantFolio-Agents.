import type { Metadata } from "next";
import { EvaluationsView } from "@/components/evaluations-view";
import { Accent, Eyebrow } from "@/components/ui";

export const metadata: Metadata = { title: "Quality" };

export default function EvaluationsPage() {
  return (
    <div className="hero-glow">
      <div className="mx-auto max-w-6xl px-4 pt-16 pb-24 sm:px-6">
        <div className="flex flex-col items-center text-center">
          <Eyebrow>Measured, not claimed</Eyebrow>
          <h1 className="display mt-6 text-5xl font-semibold sm:text-7xl">
            How good is it, <Accent>really</Accent>?
          </h1>
          <p className="mt-6 max-w-2xl text-lg text-muted-foreground">
            Two experiments, re-run from scripts: a test set of questions with known answers for the search engine, and
            the quantum computer against the exact answer for every client.
          </p>
        </div>
        <EvaluationsView />
      </div>
    </div>
  );
}

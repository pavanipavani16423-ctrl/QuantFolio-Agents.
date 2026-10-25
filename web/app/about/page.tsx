import type { Metadata } from "next";
import Link from "next/link";
import { EvaluationsView } from "@/components/evaluations-view";
import { SystemView } from "@/components/system-view";
import { Accent, cn } from "@/components/ui";

export const metadata: Metadata = { title: "About" };

const TABS = [
  { key: "how", label: "How it works" },
  { key: "results", label: "Test results" },
];

export default async function About({ searchParams }: PageProps<"/about">) {
  const { tab } = await searchParams;
  const active = tab === "results" ? "results" : "how";
  return (
    <div className="hero-glow">
      <div className="mx-auto max-w-6xl px-4 pt-14 pb-24 sm:px-6">
        <div className="flex flex-col items-center text-center">
          <h1 className="display text-4xl font-semibold sm:text-6xl">
            About the <Accent>team</Accent>
          </h1>
          <p className="mt-4 max-w-xl text-muted-foreground">
            How the agents work, and how well they did in tests.
          </p>
          <nav className="mt-8 inline-flex rounded-full border bg-card p-1" aria-label="About sections">
            {TABS.map((t) => (
              <Link
                key={t.key}
                href={t.key === "how" ? "/about" : "/about?tab=results"}
                className={cn(
                  "rounded-full px-5 py-2 text-sm",
                  active === t.key ? "bg-foreground font-semibold text-background" : "text-muted-foreground hover:text-foreground",
                )}
              >
                {t.label}
              </Link>
            ))}
          </nav>
        </div>
        {active === "how" ? <SystemView /> : <EvaluationsView />}
      </div>
    </div>
  );
}

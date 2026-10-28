import { FileSearch, Scale, UserCheck } from "lucide-react";
import { RecentRuns } from "@/components/home/recent-runs";
import { StartPanel } from "@/components/home/start-panel";
import { Accent } from "@/components/ui";

const STEPS = [
  { icon: FileSearch, title: "Reads the reports", body: "Annual reports of US (SEC) and Indian (SEBI) companies." },
  { icon: Scale, title: "Picks the stocks", body: "Checks every combination against the client's rules, then double-checks." },
  { icon: UserCheck, title: "You decide", body: "Approve, change or reject. It learns from your changes." },
];

export default function Home() {
  return (
    <div className="hero-glow">
      <div className="mx-auto max-w-5xl px-4 pt-14 pb-20 sm:px-6 sm:pt-20">
        <header className="text-center">
          <p className="text-sm font-medium text-accent">Your AI investment team</p>
          <h1 className="display mt-3 text-4xl font-semibold sm:text-6xl">
            Rebalance a portfolio, <Accent>with reasons</Accent>.
          </h1>
          <p className="mx-auto mt-4 max-w-xl text-muted-foreground">
            Choose a client, ask a question, and the agents prepare a plan you can check and approve.
          </p>
        </header>

        <div id="start" className="mt-10 scroll-mt-24">
          <StartPanel />
        </div>

        <ol className="mt-12 grid gap-3 sm:grid-cols-3">
          {STEPS.map((s, i) => (
            <li key={s.title} className="flex gap-3 rounded-2xl p-4">
              <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-accent-soft text-accent">
                <s.icon className="size-5" />
              </span>
              <div>
                <p className="font-semibold">
                  {i + 1}. {s.title}
                </p>
                <p className="mt-0.5 text-sm text-muted-foreground">{s.body}</p>
              </div>
            </li>
          ))}
        </ol>

        <div className="mt-14">
          <RecentRuns />
        </div>
      </div>
    </div>
  );
}

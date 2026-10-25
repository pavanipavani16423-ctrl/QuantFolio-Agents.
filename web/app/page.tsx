import { ArrowRight, Atom, FileSearch, ShieldCheck, UserCheck } from "lucide-react";
import { RecentRuns } from "@/components/home/recent-runs";
import { StartPanel } from "@/components/home/start-panel";
import { Accent, ButtonLink, Card, Eyebrow, SectionHeading, Stat } from "@/components/ui";

const STEPS = [
  {
    icon: FileSearch,
    title: "It reads the annual reports",
    body: "A research agent searches real SEC 10-K filings of 20 large US companies and answers with sources you can click.",
  },
  {
    icon: ShieldCheck,
    title: "It learns the client's rules",
    body: "A compliance agent reads the client's investment policy and turns it into rules: how many stocks, how much in each, what to avoid.",
  },
  {
    icon: Atom,
    title: "It picks stocks two ways",
    body: "A normal computer checks every combination. A simulated quantum computer (QAOA) tries the same problem. You see both, honestly.",
  },
  {
    icon: UserCheck,
    title: "You approve every trade",
    body: "Nothing is bought or sold until a person says yes. Then the trades go to a practice (paper) account.",
  },
];

const TEAM = [
  { name: "Supervisor", role: "Decides who works next", tag: "LangGraph" },
  { name: "Intake agent", role: "Understands your request", tag: "LLM" },
  { name: "Research agent", role: "Reads 10-K filings with hybrid search", tag: "RAG + MCP" },
  { name: "Risk agent", role: "Measures how risky each stock is", tag: "A2A service" },
  { name: "Compliance agent", role: "Reads and enforces the client's rules", tag: "A2A service" },
  { name: "Optimizer agent", role: "Normal vs quantum vs hybrid", tag: "Qiskit QAOA" },
  { name: "Report writer", role: "Writes the plain-language memo", tag: "LLM" },
  { name: "Quality judge", role: "Scores the answer with RAGAS", tag: "Langfuse" },
];

export default function Home() {
  return (
    <>
      {/* hero */}
      <section className="hero-glow">
        <div className="mx-auto flex max-w-6xl flex-col items-center px-4 pt-20 pb-16 text-center sm:px-6 sm:pt-28">
          <Eyebrow>AI agents · quantum optimization · real SEC data</Eyebrow>
          <h1 className="display mt-8 text-5xl font-semibold sm:text-7xl lg:text-[96px]">
            Your investment team,
            <br />
            <Accent>on autopilot</Accent>.
          </h1>
          <p className="mt-8 max-w-2xl text-lg text-muted-foreground sm:text-xl">
            Eight AI agents read company annual reports, check the client&apos;s rules and pick a
            portfolio, once with a normal computer and once with a quantum algorithm. You approve
            before anything is traded.
          </p>
          <div className="mt-10 flex flex-col items-center gap-3 sm:flex-row">
            <ButtonLink href="/#start" size="lg">
              Run the agents <ArrowRight className="size-4" />
            </ButtonLink>
            <ButtonLink href="/how-it-works" variant="outline" size="lg">
              See how it works
            </ButtonLink>
          </div>
          <p className="mt-6 text-sm text-subtle-foreground">
            Takes about 20 seconds · paper trading only · every step traced in Langfuse
          </p>
        </div>
      </section>

      {/* stats */}
      <section className="mx-auto max-w-6xl px-4 sm:px-6">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat value="20" label="real US companies" />
          <Stat value="2,119" label="passages from SEC filings" />
          <Stat value="706" label="days of real prices" />
          <Stat value="≤ 20" label="qubits per quantum run" />
        </div>
      </section>

      {/* how it works */}
      <section className="mx-auto max-w-6xl px-4 py-24 sm:px-6">
        <SectionHeading
          eyebrow="How it works"
          title={
            <>
              Four steps, <Accent>no jargon</Accent>.
            </>
          }
          lead="This is the work a wealth-management team does by hand every quarter. The agents do it in seconds and show their work."
        />
        <div className="mt-12 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {STEPS.map((s, i) => (
            <Card key={s.title} className="flex flex-col gap-4">
              <div className="flex items-center justify-between">
                <span className="grid size-11 place-items-center rounded-2xl bg-accent-soft text-accent">
                  <s.icon className="size-5" />
                </span>
                <span className="accent-word text-3xl">{i + 1}</span>
              </div>
              <h3 className="text-lg font-semibold">{s.title}</h3>
              <p className="text-muted-foreground">{s.body}</p>
            </Card>
          ))}
        </div>
      </section>

      {/* start */}
      <section id="start" className="scroll-mt-20 bg-panel">
        <div className="mx-auto max-w-6xl px-4 py-24 sm:px-6">
          <SectionHeading
            center
            eyebrow="Try it"
            title={
              <>
                Pick a client. <Accent>Ask anything.</Accent>
              </>
            }
            lead="Three example clients with different rules. The agents rebalance their portfolio and answer your research question from the filings."
          />
          <div className="mt-12">
            <StartPanel />
          </div>
        </div>
      </section>

      {/* team */}
      <section className="mx-auto max-w-6xl px-4 py-24 sm:px-6">
        <SectionHeading
          eyebrow="Meet the team"
          title={
            <>
              Eight agents. <Accent>One job</Accent> each.
            </>
          }
          lead="The risk and compliance agents run as separate services and talk over Google's A2A protocol, as if they belonged to other teams. Tools are shared through MCP servers."
        />
        <div className="mt-12 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {TEAM.map((t) => (
            <div key={t.name} className="rounded-2xl border bg-card p-5">
              <div className="flex items-center justify-between gap-2">
                <h3 className="font-semibold">{t.name}</h3>
                <span className="rounded-full bg-panel px-2 py-0.5 text-[11px] text-muted-foreground">{t.tag}</span>
              </div>
              <p className="mt-2 text-sm text-muted-foreground">{t.role}</p>
            </div>
          ))}
        </div>
      </section>

      {/* recent */}
      <section className="mx-auto max-w-6xl px-4 pb-24 sm:px-6">
        <RecentRuns />
      </section>

      {/* honest note */}
      <section className="border-t bg-panel-2">
        <div className="mx-auto flex max-w-4xl flex-col items-center px-4 py-24 text-center sm:px-6">
          <Eyebrow>The honest part</Eyebrow>
          <h2 className="display mt-6 text-4xl font-semibold sm:text-6xl">
            Quantum is <Accent>tested</Accent>, not hyped.
          </h2>
          <p className="mt-6 max-w-2xl text-lg text-muted-foreground">
            The quantum computer here is simulated on a laptop, so it is slower than the normal one.
            The project measures where it matches the best answer and where it does not, and shows
            the numbers next to each other.
          </p>
          <ButtonLink href="/evaluations" variant="dark" size="lg" className="mt-10">
            See the measured results <ArrowRight className="size-4" />
          </ButtonLink>
        </div>
      </section>
    </>
  );
}

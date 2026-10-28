// Client-ready reports built from a run, as Markdown (download) - the same content as the UI.

import type { Run } from "./types";

const pct = (v: number | null | undefined, d = 1) => (v === null || v === undefined ? "–" : `${(v * 100).toFixed(d)}%`);

function sourcesMd(run: Run): string[] {
  const r = run.result.research;
  if (!r) return [];
  return [
    "## Sources",
    "",
    ...r.sources.map((s) => `[${s.n}] ${s.title}${s.section ? ` - ${s.section}` : ""}${s.source_url ? ` (${s.source_url})` : ""}`),
    "",
  ];
}

export function researchMarkdown(run: Run): string {
  const r = run.result.research;
  if (!r) return "";
  const lines = [
    `# Research report: ${r.question}`,
    "",
    `Client: ${run.client_name} · ${run.market_name} · prepared ${new Date(run.created_at).toLocaleDateString()}`,
    `Based only on the companies' own disclosures: ${run.research_sources}.`,
    "",
    "## Summary",
    "",
    r.answer,
    "",
  ];
  const figures = Object.fromEntries((r.key_figures ?? []).map((f) => [f.ticker, f]));
  for (const c of r.companies ?? []) {
    const f = figures[c.ticker];
    lines.push(`## ${f?.company ?? c.ticker} (${c.ticker})`, "");
    if (f) {
      lines.push(`Key numbers, fiscal year ${f.fiscal_year} (from ${f.source}):`, "");
      lines.push(...f.items.map((i) => `- ${i.label}: ${i.value}${i.note ? ` (${i.note})` : ""}`), "");
    }
    if (c.key_points.length) lines.push("**Key points**", "", ...c.key_points.map((p) => `- ${p}`), "");
    if (c.risks.length) lines.push("**Risks**", "", ...c.risks.map((p) => `- ${p}`), "");
  }
  if (r.not_covered?.length) lines.push("## Not covered by the sources", "", ...r.not_covered.map((x) => `- ${x}`), "");
  lines.push(...sourcesMd(run));
  lines.push("_Research only; not investment advice. Every cited sentence was checked against its source._");
  return lines.join("\n");
}

export function clientReportMarkdown(run: Run): string {
  const res = run.result;
  const memo = res.memo;
  const opt = res.optimization;
  const rec = opt ? opt.proposals[opt.recommended] : undefined;
  const lines = [`# ${run.client_name}: portfolio review`, "", `${run.market_name} · ${new Date(run.created_at).toLocaleDateString()}`, ""];
  if (memo) {
    lines.push(`## ${memo.headline}`, "", memo.summary, "");
    if (rec) {
      lines.push("| Expected yearly return | Expected ups and downs | Stocks |", "|---|---|---|");
      lines.push(`| ${pct(rec.expected_return)} | ${pct(rec.volatility)} | ${rec.selected.length} |`, "");
      lines.push("## The portfolio", "", "| Stock | Weight |", "|---|---|");
      lines.push(...Object.entries(rec.weights).sort((a, b) => b[1] - a[1]).map(([t, w]) => `| ${t} | ${pct(w)} |`), "");
    }
    lines.push("## What changes", "", ...memo.key_changes.map((c) => `- ${c}`), "");
    lines.push("## Risks to know", "", ...memo.risks.map((c) => `- ${c}`), "");
  }
  if (res.compliance) {
    lines.push("## Client rules", "", ...res.compliance.checks.map((c) => `- ${c.passed ? "✓" : "✗"} ${c.detail}`), "");
  }
  const research = researchMarkdown(run);
  if (research) lines.push("---", "", research.replace(/^# /, "# Appendix - "), "");
  else lines.push(...sourcesMd(run));
  lines.push("_Paper trading only; not investment advice. Past performance does not guarantee future results._");
  return lines.join("\n");
}

export function download(filename: string, text: string) {
  const blob = new Blob([text], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

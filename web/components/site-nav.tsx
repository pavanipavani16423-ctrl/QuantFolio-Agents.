"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, useSyncExternalStore } from "react";
import { Moon, Sun } from "lucide-react";
import { cn } from "@/components/ui";
import { api, type Health } from "@/lib/api";

const LINKS = [
  { href: "/", label: "New request" },
  { href: "/history", label: "History" },
  { href: "/about", label: "About" },
];

function subscribeTheme(onChange: () => void) {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
  return () => observer.disconnect();
}

function ThemeToggle() {
  const dark = useSyncExternalStore(
    subscribeTheme,
    () => document.documentElement.classList.contains("dark"),
    () => false,
  );
  function toggle() {
    const next = !dark;
    const root = document.documentElement;
    root.classList.toggle("dark", next);
    root.dataset.theme = next ? "dark" : "light";
    try {
      localStorage.setItem("theme", next ? "dark" : "light");
    } catch {}
  }
  return (
    <button
      onClick={toggle}
      className="grid size-10 place-items-center rounded-full border border-border-strong bg-card hover:bg-panel"
      aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
    >
      {dark ? <Sun className="size-4" /> : <Moon className="size-4" />}
    </button>
  );
}

function HealthDot() {
  const [health, setHealth] = useState<Health | null>(null);
  const [down, setDown] = useState(false);
  useEffect(() => {
    let alive = true;
    const load = () =>
      api
        .health()
        .then((h) => alive && (setHealth(h), setDown(false)))
        .catch(() => alive && setDown(true));
    load();
    const t = setInterval(load, 20000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);
  const label = down
    ? "Backend offline"
    : !health
      ? "Connecting"
      : health.llm.startsWith("rule-based")
        ? "Ready · offline AI"
        : "Ready · " + health.llm.split(":")[0];
  return (
    <span
      className="hidden items-center gap-2 text-xs text-muted-foreground lg:inline-flex"
      title={
        health
          ? `AI model: ${health.llm}\nQuality judge: ${health.judge ?? "none"}\nLangfuse: ${health.langfuse.enabled ? "on" : "off"}`
          : undefined
      }
    >
      <span
        className={cn(
          "size-2 rounded-full",
          down ? "bg-critical" : health ? "bg-good" : "bg-subtle-foreground pulse-dot",
        )}
      />
      {label}
    </span>
  );
}

export function SiteNav() {
  const path = usePathname();
  return (
    <header className="sticky top-0 z-40 border-b bg-background/80 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-2 px-3 sm:gap-3 sm:px-6">
        <Link href="/" className="flex items-center gap-2.5" aria-label="QuantFolio Agents home">
          <span className="grid size-9 place-items-center rounded-lg bg-accent font-serif text-xl italic text-white">
            Q
          </span>
          <span className="hidden leading-tight sm:block">
            <span className="block text-[15px]">
              <span className="font-serif text-lg italic">Quant</span>
              <span className="font-semibold">Folio</span>
            </span>
            <span className="block text-[10px] uppercase tracking-[0.14em] text-subtle-foreground">
              AI investment team
            </span>
          </span>
        </Link>
        <nav className="flex items-center gap-0.5 sm:gap-1" aria-label="Main">
          {LINKS.map((l) => {
            const active = l.href === "/" ? path === "/" : path.startsWith(l.href);
            return (
              <Link
                key={l.href}
                href={l.href}
                className={cn(
                  "whitespace-nowrap rounded-full px-2 py-2 text-[13px] sm:px-3 sm:text-sm",
                  active ? "bg-panel font-semibold" : "text-muted-foreground hover:text-foreground",
                )}
              >
                {l.label}
              </Link>
            );
          })}
        </nav>
        <div className="flex items-center gap-3">
          <HealthDot />
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}

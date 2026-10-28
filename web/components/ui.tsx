import { clsx, type ClassValue } from "clsx";
import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function Eyebrow({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex w-fit items-center gap-2 rounded-full bg-accent-soft px-3 py-1 text-xs font-semibold uppercase tracking-[0.12em] text-accent",
        className,
      )}
    >
      <span className="size-1.5 rounded-full bg-accent" aria-hidden />
      {children}
    </span>
  );
}

/** Serif italic accent word in a headline. */
export function Accent({ children }: { children: ReactNode }) {
  return <span className="accent-word">{children}</span>;
}

export function Card({ className, ...props }: ComponentProps<"div">) {
  return <div className={cn("rounded-3xl border bg-card p-6", className)} {...props} />;
}

export function Panel({ className, ...props }: ComponentProps<"div">) {
  return <div className={cn("rounded-[28px] bg-panel p-4 sm:p-6", className)} {...props} />;
}

type ButtonVariant = "primary" | "dark" | "outline" | "ghost";

const variants: Record<ButtonVariant, string> = {
  primary:
    "bg-accent text-white shadow-[0_8px_24px_-8px_var(--accent)] hover:bg-accent-strong disabled:shadow-none",
  dark: "bg-foreground text-background hover:opacity-90",
  outline: "border border-border-strong bg-card hover:bg-panel",
  ghost: "hover:bg-panel",
};

export function buttonClass(variant: ButtonVariant = "primary", size: "md" | "lg" = "md") {
  return cn(
    "inline-flex items-center justify-center gap-2 rounded-full font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
    size === "lg" ? "h-12 px-6 text-base" : "h-10 px-4 text-sm",
    variants[variant],
  );
}

export function Button({
  variant = "primary",
  size = "md",
  className,
  ...props
}: ComponentProps<"button"> & { variant?: ButtonVariant; size?: "md" | "lg" }) {
  return <button className={cn(buttonClass(variant, size), className)} {...props} />;
}

export function ButtonLink({
  variant = "primary",
  size = "md",
  className,
  ...props
}: ComponentProps<typeof Link> & { variant?: ButtonVariant; size?: "md" | "lg" }) {
  return <Link className={cn(buttonClass(variant, size), className)} {...props} />;
}

export function SectionHeading({
  eyebrow,
  title,
  lead,
  center = false,
}: {
  eyebrow?: string;
  title: ReactNode;
  lead?: ReactNode;
  center?: boolean;
}) {
  return (
    <div className={cn("flex flex-col gap-4", center && "items-center text-center")}>
      {eyebrow && <Eyebrow>{eyebrow}</Eyebrow>}
      <h2 className="display text-4xl font-semibold sm:text-5xl">{title}</h2>
      {lead && <p className="max-w-2xl text-lg text-muted-foreground">{lead}</p>}
    </div>
  );
}

export function Stat({ value, label }: { value: ReactNode; label: ReactNode }) {
  return (
    <div className="rounded-2xl bg-panel-2 px-4 py-5 text-center">
      <div className="accent-word tabular text-4xl">{value}</div>
      <div className="mt-1 text-sm text-muted-foreground">{label}</div>
    </div>
  );
}

const toneClass = {
  neutral: "bg-panel text-muted-foreground",
  good: "bg-good-soft text-good",
  warning: "bg-warning-soft text-warning",
  critical: "bg-critical-soft text-critical",
  accent: "bg-accent-soft text-accent",
} as const;

export type Tone = keyof typeof toneClass;

export function Badge({
  tone = "neutral",
  children,
  className,
}: {
  tone?: Tone;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium",
        toneClass[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-2xl border border-dashed p-8 text-center text-sm text-muted-foreground">
      {children}
    </div>
  );
}

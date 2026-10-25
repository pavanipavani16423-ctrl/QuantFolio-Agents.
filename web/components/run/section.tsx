import type { ReactNode } from "react";
import { cn } from "@/components/ui";

export function RunSection({
  id,
  eyebrow,
  title,
  lead,
  right,
  children,
  className,
}: {
  id?: string;
  eyebrow?: string;
  title: ReactNode;
  lead?: ReactNode;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section id={id} className={cn("scroll-mt-24 rounded-3xl border bg-card p-5 sm:p-6", className)}>
      <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          {eyebrow && (
            <p className="mb-1 text-xs font-semibold uppercase tracking-[0.12em] text-accent">{eyebrow}</p>
          )}
          <h2 className="text-xl font-semibold tracking-tight sm:text-2xl">{title}</h2>
          {lead && <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{lead}</p>}
        </div>
        {right}
      </div>
      {children}
    </section>
  );
}

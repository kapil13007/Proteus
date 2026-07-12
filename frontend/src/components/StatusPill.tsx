import { cn } from "@/lib/utils";
import type { RunStatus } from "@/lib/types";

const CONFIG: Record<RunStatus, { label: string; classes: string; dot: string; pulse?: boolean }> = {
  running: {
    label: "Running",
    classes: "border-primary/40 bg-primary/10 text-primary",
    dot: "bg-primary",
    pulse: true,
  },
  awaiting_review: {
    label: "Awaiting review",
    classes: "border-info/40 bg-info/10 text-info",
    dot: "bg-info",
  },
  succeeded: {
    label: "Succeeded",
    classes: "border-success/40 bg-success/10 text-success",
    dot: "bg-success",
  },
  failed: {
    label: "Failed",
    classes: "border-destructive/40 bg-destructive/10 text-destructive",
    dot: "bg-destructive",
  },
  rejected: {
    label: "Rejected",
    classes: "border-border bg-elevated text-muted-foreground",
    dot: "bg-muted-foreground",
  },
};

export function StatusPill({ status, className }: { status: RunStatus; className?: string }) {
  const c = CONFIG[status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 font-mono text-xs",
        c.classes,
        className,
      )}
    >
      <span className={cn("size-1.5 rounded-full", c.dot, c.pulse && "pulse-dot")} />
      {c.label}
    </span>
  );
}
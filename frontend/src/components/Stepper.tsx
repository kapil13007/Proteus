import { Check, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { STEP_LABELS } from "@/lib/types";
import type { Run } from "@/lib/types";

type StepState = "pending" | "active" | "done" | "failed";

function stepState(run: Run, index: number): StepState {
  const finished = run.status === "succeeded";
  if (finished) return "done";
  if (index < run.currentStep) return "done";
  if (index === run.currentStep) {
    if (run.stepFailed || run.status === "failed") return "failed";
    if (run.status === "rejected") return "failed";
    return "active";
  }
  return "pending";
}

export function Stepper({ run }: { run: Run }) {
  return (
    <ol className="relative">
      {STEP_LABELS.map((label, i) => {
        const state = stepState(run, i);
        const isLast = i === STEP_LABELS.length - 1;
        return (
          <li key={label} className="relative flex gap-3 pb-7 last:pb-0">
            {!isLast && (
              <span
                className={cn(
                  "absolute top-6 left-[11px] h-[calc(100%-1.5rem)] w-px",
                  state === "done" ? "bg-success/40" : "bg-border",
                )}
              />
            )}
            <span
              className={cn(
                "z-10 flex size-6 shrink-0 items-center justify-center rounded-full border",
                state === "done" && "border-success/50 bg-success/10 text-success",
                state === "active" && "border-primary/50 bg-primary/10",
                state === "failed" && "border-destructive/50 bg-destructive/10 text-destructive",
                state === "pending" && "border-border bg-card text-muted-foreground/40",
              )}
            >
              {state === "done" && <Check className="size-3.5" strokeWidth={2.5} />}
              {state === "failed" && <X className="size-3.5" strokeWidth={2.5} />}
              {state === "active" && <span className="size-2 rounded-full bg-primary pulse-dot" />}
              {state === "pending" && <span className="size-1.5 rounded-full bg-current" />}
            </span>
            <div className="pt-0.5">
              <p
                className={cn(
                  "text-sm",
                  state === "active" && "font-medium text-primary",
                  state === "done" && "text-foreground",
                  state === "failed" && "text-destructive",
                  state === "pending" && "text-muted-foreground",
                )}
              >
                {label}
              </p>
              {run.attempt && run.attempt.step === i && (
                <p className="mt-0.5 font-mono text-xs text-muted-foreground">
                  attempt {run.attempt.current} of {run.attempt.max}
                </p>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
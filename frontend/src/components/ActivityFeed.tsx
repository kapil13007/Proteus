import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";
import type { ActivityEntry } from "@/lib/types";

const PREFIX: Record<ActivityEntry["kind"], string> = {
  thought: "\u25c6",
  tool_call: "\u2192",
  tool_result: "\u2190",
  tool_error: "\u2190",
};

function entryClass(kind: ActivityEntry["kind"]) {
  switch (kind) {
    case "thought":
      return "text-muted-foreground italic";
    case "tool_call":
      return "text-info";
    case "tool_result":
      return "text-success";
    case "tool_error":
      return "text-destructive";
  }
}

export function ActivityFeed({
  entries,
  live = false,
  className,
  maxHeight = "32rem",
}: {
  entries: ActivityEntry[];
  live?: boolean;
  className?: string;
  maxHeight?: string;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!live) return;
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [entries.length, live]);

  return (
    <div
      className={cn(
        "rounded-lg border border-l-2 border-l-primary bg-terminal",
        className,
      )}
    >
      <div className="flex items-center justify-between border-b px-4 py-2.5">
        <span className="font-mono text-xs text-muted-foreground">agent activity</span>
        {live && (
          <span className="inline-flex items-center gap-1.5 font-mono text-xs text-primary">
            <span className="size-1.5 rounded-full bg-primary pulse-dot" />
            live
          </span>
        )}
      </div>
      <div ref={scrollRef} className="overflow-y-auto p-4" style={{ maxHeight }}>
        {entries.length === 0 ? (
          <p className="font-mono text-xs text-muted-foreground">
            Waiting for the agent to start…
          </p>
        ) : (
          <ol className="space-y-2">
            {entries.map((entry) => (
              <li
                key={entry.id}
                className={cn("flex gap-3 font-mono text-[13px] leading-5", live && "feed-enter")}
              >
                <span className="shrink-0 tabular-nums text-muted-foreground/50">{entry.ts}</span>
                <span className={cn("shrink-0", entryClass(entry.kind))}>
                  {PREFIX[entry.kind]}
                </span>
                <span className={entryClass(entry.kind)}>
                  {entry.kind === "tool_error" ? entry.text : entry.text}
                </span>
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}
import type { RunMetrics } from "./types";

export function timeAgo(ts: number): string {
  const s = Math.max(1, Math.round((Date.now() - ts) / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.round(h / 24);
  return `${d}d ago`;
}

export function formatDuration(sec: number | null | undefined): string {
  if (sec === null || sec === undefined) return "—";
  if (sec < 10) return `${sec.toFixed(1)}s`;
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  if (m === 0) return `${s}s`;
  return `${m}m ${String(s).padStart(2, "0")}s`;
}

export function formatMs(ms: number | undefined): string {
  if (ms === undefined) return "—";
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

export function formatBytes(bytes: number | undefined): string {
  if (bytes === undefined) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatUsd(usd: number | undefined): string {
  if (usd === undefined) return "—";
  return usd === 0 ? "$0" : `$${usd < 0.01 ? usd.toFixed(5) : usd.toFixed(2)}`;
}

export function formatTokens(n: number | undefined): string {
  return (n ?? 0).toLocaleString("en-US");
}

/** Machine time: the sum of every recorded stage (excludes time spent waiting for a human). */
export function agentMs(metrics: RunMetrics | undefined): number | undefined {
  const t = metrics?.timingsMs;
  if (!t) return undefined;
  return Object.values(t).reduce((a, b) => a + b, 0);
}

/**
 * Mapfl0w API client — real HTTP against the FastAPI backend (session cookie auth).
 *
 * Live updates are polling behind subscribeRun(): fast while the agent is working,
 * slow while a run waits for review, and stopped once a run is finished.
 */
import type { Run, RunSummary, SystemStatus } from "./types";

export const API_BASE =
  (import.meta.env.VITE_API_URL as string | undefined) ?? "http://localhost:8000";

const cache = new Map<string, Run>();
const listeners = new Map<string, Set<() => void>>();
const pollers = new Map<string, ReturnType<typeof setTimeout>>();

const TERMINAL = ["succeeded", "failed", "rejected"];

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { ...init, credentials: "include" });
  if (!res.ok) {
    // FastAPI error responses carry {"detail": "..."} — surface that when present.
    const message = await res
      .json()
      .then((body: { detail?: string }) => body.detail)
      .catch(() => undefined);
    throw new Error(message || `${init?.method ?? "GET"} ${path} → ${res.status}`);
  }
  return res.json() as Promise<T>;
}

function postJson<T>(path: string, body: unknown): Promise<T> {
  return fetchJson<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** GET /runs — light summaries for the dashboard. */
export function listRuns(): Promise<RunSummary[]> {
  return fetchJson<RunSummary[]>("/runs");
}

/** GET /runs/{id} */
export async function getRun(id: string): Promise<Run | undefined> {
  try {
    const run = await fetchJson<Run>(`/runs/${id}`);
    cache.set(id, run);
    listeners.get(id)?.forEach((cb) => cb());
    return run;
  } catch {
    return undefined;
  }
}

export type UploadSlot = "source" | "target" | "sttm" | "repo" | "udf" | "env";

export interface UploadSlotFile {
  slot: UploadSlot;
  file: File;
}

/** POST /runs — multipart with the uploaded context files. Returns { run_id }. */
export async function createRun(files: UploadSlotFile[]): Promise<{ run_id: string }> {
  const form = new FormData();
  for (const { slot, file } of files) form.append(slot, file, file.name);
  return fetchJson<{ run_id: string }>("/runs", { method: "POST", body: form });
}

/** GET /samples/{slot} — the demo inputs, as File objects ready to upload. */
export async function loadSampleFiles(): Promise<UploadSlotFile[]> {
  const names = await fetchJson<Record<UploadSlot, string>>("/samples");
  return Promise.all(
    (Object.entries(names) as [UploadSlot, string][]).map(async ([slot, name]) => {
      const res = await fetch(`${API_BASE}/samples/${slot}`, { credentials: "include" });
      if (!res.ok) throw new Error(`could not load sample ${name}`);
      return { slot, file: new File([await res.blob()], name) };
    }),
  );
}

export interface Override {
  row: number;
  expression: string;
}

/** POST /runs/{id}/revise — reviewer overrides and/or free-text feedback for the agent. */
export async function reviseRun(
  id: string,
  overrides: Override[],
  feedback: string,
): Promise<void> {
  await postJson(`/runs/${id}/revise`, { overrides, feedback });
  kick(id);
}

/** POST /runs/{id}/approve — execute, audit, publish. */
export async function approveRun(id: string): Promise<void> {
  await postJson(`/runs/${id}/approve`, {});
  kick(id);
}

/** POST /runs/{id}/reject — terminal. */
export async function rejectRun(id: string, feedback: string): Promise<void> {
  await postJson(`/runs/${id}/reject`, { feedback });
  kick(id);
}

/** The generated files at their repo paths plus a decision log, as a zip. */
export function bundleUrl(id: string): string {
  return `${API_BASE}/runs/${id}/bundle.zip`;
}

/** GET /system/status — real configuration, never secrets. */
export function getSystemStatus(): Promise<SystemStatus> {
  return fetchJson<SystemStatus>("/system/status");
}

function pollDelay(run: Run | undefined): number | null {
  if (!run) return 1000;
  if (TERMINAL.includes(run.status)) return null;
  return run.status === "running" ? 1000 : 4000;
}

function schedule(id: string, delay: number): void {
  const pending = pollers.get(id);
  if (pending) clearTimeout(pending);
  pollers.set(
    id,
    setTimeout(async () => {
      await getRun(id);
      if (!listeners.has(id)) return;
      const next = pollDelay(cache.get(id));
      if (next === null) pollers.delete(id);
      else schedule(id, next);
    }, delay),
  );
}

/** Poll the run while anyone is subscribed. */
export function subscribeRun(id: string, cb: () => void): () => void {
  const set = listeners.get(id) ?? new Set();
  set.add(cb);
  listeners.set(id, set);
  if (!pollers.has(id)) schedule(id, 0);

  return () => {
    set.delete(cb);
    if (set.size === 0) {
      const t = pollers.get(id);
      if (t) clearTimeout(t);
      pollers.delete(id);
      listeners.delete(id);
    }
  };
}

/** After an action (approve / revise), poll now instead of waiting for the slow review cadence. */
function kick(id: string): void {
  if (listeners.has(id)) schedule(id, 0);
  else void getRun(id);
}

/** Synchronous snapshot from the cache. */
export function peekRun(id: string): Run | undefined {
  return cache.get(id);
}

// --------------------------------------------------------------------------- //
//  Auth
// --------------------------------------------------------------------------- //

export interface AuthUser {
  id: string;
  email: string;
  name: string;
}

/** GET /auth/me — returns null instead of throwing when unauthenticated. */
export async function getCurrentUser(): Promise<AuthUser | null> {
  try {
    return await fetchJson<AuthUser>("/auth/me");
  } catch {
    return null;
  }
}

export async function login(email: string, password: string): Promise<AuthUser> {
  return postJson<AuthUser>("/auth/login", { email, password });
}

export async function register(email: string, password: string, name?: string): Promise<AuthUser> {
  return postJson<AuthUser>("/auth/register", { email, password, name: name ?? "" });
}

export async function logout(): Promise<void> {
  await fetchJson("/auth/logout", { method: "POST" });
}

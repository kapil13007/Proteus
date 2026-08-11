/**
 * Mapfl0w API client — real HTTP against the FastAPI backend.
 *
 * Exports keep the exact signatures the pages already use. Live updates are
 * implemented as polling (GET /runs/{id} every 1.2s) behind subscribeRun().
 */
import type { Run } from "./types";

const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? "http://localhost:8000";

// Local cache so peekRun() stays synchronous for the pages
const cache = new Map<string, Run>();
const listeners = new Map<string, Set<() => void>>();
const pollers = new Map<string, ReturnType<typeof setInterval>>();

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { ...init, credentials: "include" });
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

/** GET /runs */
export async function listRuns(): Promise<Run[]> {
  const runs = await fetchJson<Run[]>("/runs");
  for (const r of runs) cache.set(r.id, r);
  return runs;
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

export interface UploadSlotFile {
  slot: "source" | "target" | "sttm" | "repo" | "udf";
  file: File;
}

/** POST /runs — multipart with the 5 uploaded files. Returns { run_id }. */
export async function createRun(files: UploadSlotFile[]): Promise<{ run_id: string }> {
  const form = new FormData();
  for (const { slot, file } of files) form.append(slot, file, file.name);
  return fetchJson<{ run_id: string }>("/runs", { method: "POST", body: form });
}

/** POST /runs/{id}/approve — optionally sends the reviewer-edited .sqlx */
export async function approveRun(id: string, editedSqlx?: string): Promise<void> {
  await fetchJson(`/runs/${id}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sqlx: editedSqlx ?? null }),
  });
  void getRun(id);
}

/** POST /runs/{id}/reject */
export async function rejectRun(id: string, feedback: string): Promise<void> {
  await fetchJson(`/runs/${id}/reject`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ feedback }),
  });
  void getRun(id);
}

/** Poll the run while anyone is subscribed. */
export function subscribeRun(id: string, cb: () => void): () => void {
  const set = listeners.get(id) ?? new Set();
  set.add(cb);
  listeners.set(id, set);

  if (!pollers.has(id)) {
    void getRun(id);
    pollers.set(
      id,
      setInterval(() => {
        const run = cache.get(id);
        // Stop burning requests once the run is terminal
        if (run && ["succeeded", "failed", "rejected"].includes(run.status)) {
          const done = ["succeeded", "failed", "rejected"];
          if (done.includes(run.status)) {
            clearInterval(pollers.get(id));
            pollers.delete(id);
            return;
          }
        }
        void getRun(id);
      }, 1200),
    );
  }

  return () => {
    set.delete(cb);
    if (set.size === 0) {
      const t = pollers.get(id);
      if (t) clearInterval(t);
      pollers.delete(id);
      listeners.delete(id);
    }
  };
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
  return fetchJson<AuthUser>("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
}

export async function register(email: string, password: string, name?: string): Promise<AuthUser> {
  return fetchJson<AuthUser>("/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, name: name ?? "" }),
  });
}

export async function logout(): Promise<void> {
  await fetchJson("/auth/logout", { method: "POST" });
}

/** Placeholder previews for slots with binary uploads (e.g. Excel). */
export const FILE_PREVIEW_FALLBACK: Record<string, string> = {
  source: "(no preview available)",
  target: "(no preview available)",
  sttm: "(binary spreadsheet — preview unavailable)",
  repo: "(no preview available)",
  udf: "(no preview available)",
};

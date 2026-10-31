"use client";

import { useCallback, useEffect, useRef, useState } from "react";

// ------------------------------------------------------------------- types
export type Project = { id: number; name: string; description: string; is_demo: boolean };
export type Agent = {
  id: number; name: string; role: string; runtime_type: string;
  status: string; last_seen_at: string | null;
};
export type Task = {
  id: number; key: string; title: string; description: string; kind: string;
  status: string; priority: string; requires_approval: boolean; attempts: number;
  assigned_agent_id: number | null; created_by: string; created_at: string;
  updated_at: string; completion_summary: string; depends_on: number[];
};
export type Message = {
  id: number; task_id: number | null; sender_type: string; sender_name: string;
  message_type: string; content: string; structured: Record<string, unknown> | null;
  delivered_via: string; thread_id: string; created_at: string;
};
export type Approval = {
  id: number; task_id: number; requested_by: string; approved_by: string;
  status: string; decision_reason: string; created_at: string; decided_at: string | null;
};
export type TaskEvent = {
  id: number; task_id: number; event_type: string; actor: string;
  event_data: Record<string, unknown>; created_at: string;
};
export type Run = {
  id: number; task_id: number; status: string; started_at: string;
  finished_at: string | null; output_summary: string; error_summary: string;
};
export type Metrics = {
  total_tasks: number; completed: number; in_progress: number; blocked: number;
  pending_approvals: number; active_agents: number;
};
export type SwitchStatus = { configured: boolean; state: string; room_id?: string; last_error?: string };

// ------------------------------------------------------------------ fetchers
export async function api<T>(path: string): Promise<T> {
  const r = await fetch(`/api${path}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

export async function post<T>(path: string, body: unknown, method = "POST"): Promise<T> {
  const r = await fetch(`/api${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

// -------------------------------------------------------------------- hooks
/** Reloads `load` on mount and whenever the backend publishes an SSE event. */
export function useLive<T>(load: () => Promise<T>): { data: T | null; reload: () => void; error: string } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const reload = useCallback(() => {
    load().then((d) => { setData(d); setError(""); }).catch((e) => setError(String(e)));
  }, [load]);

  useEffect(() => {
    reload();
    const es = new EventSource("/api/stream");
    es.onmessage = () => {
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(reload, 250); // coalesce bursts
    };
    return () => { es.close(); if (timer.current) clearTimeout(timer.current); };
  }, [reload]);

  return { data, reload, error };
}

export function useProjectId(): number | null {
  const [id, setId] = useState<number | null>(null);
  useEffect(() => {
    api<Project[]>("/projects").then((ps) => ps.length && setId(ps[0].id)).catch(() => {});
  }, []);
  return id;
}

// ------------------------------------------------------------------ display
export const STATUS_META: Record<string, { label: string; cls: string; dot: string }> = {
  backlog:          { label: "Backlog",      cls: "bg-slate-500/15 text-slate-300",   dot: "bg-slate-400" },
  ready:            { label: "Ready",        cls: "bg-sky-500/15 text-sky-300",       dot: "bg-sky-400" },
  in_progress:      { label: "In Progress",  cls: "bg-indigo-500/15 text-indigo-300", dot: "bg-indigo-400" },
  blocked:          { label: "Blocked",      cls: "bg-red-500/15 text-red-300",       dot: "bg-red-400" },
  in_review:        { label: "In Review",    cls: "bg-amber-500/15 text-amber-300",   dot: "bg-amber-400" },
  waiting_approval: { label: "Needs Approval", cls: "bg-violet-500/15 text-violet-300", dot: "bg-violet-400" },
  completed:        { label: "Completed",    cls: "bg-emerald-500/15 text-emerald-300", dot: "bg-emerald-400" },
  cancelled:        { label: "Cancelled",    cls: "bg-zinc-500/15 text-zinc-400",     dot: "bg-zinc-500" },
  failed:           { label: "Failed",       cls: "bg-rose-500/15 text-rose-300",     dot: "bg-rose-400" },
};

export const AGENT_STATUS_CLS: Record<string, string> = {
  idle: "text-slate-300", working: "text-indigo-300", waiting: "text-sky-300",
  blocked: "text-red-300", reviewing: "text-amber-300", offline: "text-zinc-500",
};

export function timeAgo(iso: string | null): string {
  if (!iso) return "never";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return `${Math.max(0, Math.floor(s))}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return new Date(iso).toLocaleDateString();
}

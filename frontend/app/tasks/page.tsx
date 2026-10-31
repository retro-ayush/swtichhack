"use client";

import { Badge, Panel } from "@/components/ui";
import {
  Agent, api, post, Run, Task, TaskEvent, timeAgo, useLive, useProjectId,
} from "@/lib/api";
import { useCallback, useEffect, useState } from "react";

const COLUMNS = ["backlog", "ready", "in_progress", "blocked", "in_review", "waiting_approval", "completed"];
const PRIORITY_DOT: Record<string, string> = {
  low: "bg-slate-500", medium: "bg-sky-400", high: "bg-amber-400", critical: "bg-red-500",
};

function Detail({ task, agents, tasks, onClose, onChanged }: {
  task: Task; agents: Agent[]; tasks: Task[]; onClose: () => void; onChanged: () => void;
}) {
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [err, setErr] = useState("");

  useEffect(() => {
    api<TaskEvent[]>(`/tasks/${task.id}/events`).then(setEvents).catch(() => {});
    api<Run[]>(`/tasks/${task.id}/runs`).then(setRuns).catch(() => {});
  }, [task.id, task.updated_at]);

  const act = async (fn: () => Promise<unknown>) => {
    setErr("");
    try { await fn(); onChanged(); } catch (e) { setErr(String(e)); }
  };
  const agentName = (id: number | null) => agents.find((a) => a.id === id)?.name ?? "unassigned";

  return (
    <div className="w-96 shrink-0 space-y-4 overflow-y-auto rounded-xl border border-edge bg-panel p-4">
      <div className="flex items-start justify-between">
        <div>
          <div className="font-mono text-xs text-muted">{task.key} · {task.kind} · attempt {task.attempts}</div>
          <h3 className="mt-1 font-semibold">{task.title}</h3>
        </div>
        <button onClick={onClose} className="text-muted hover:text-foreground">✕</button>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Badge status={task.status} />
        {task.requires_approval && (
          <span className="rounded bg-violet-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-violet-300">HUMAN APPROVAL REQUIRED</span>
        )}
      </div>
      {task.description && <p className="text-sm text-muted">{task.description}</p>}
      <div className="text-xs text-muted">
        <div>Assigned: <span className="text-foreground">{agentName(task.assigned_agent_id)}</span></div>
        <div>Depends on: {task.depends_on.length
          ? task.depends_on.map((d) => tasks.find((t) => t.id === d)?.key ?? `T-${d}`).join(", ")
          : "nothing"}</div>
        {task.completion_summary && <div>Done: {task.completion_summary}</div>}
      </div>

      <div className="flex flex-wrap gap-2">
        <select
          value={task.priority}
          onChange={(e) => act(() => post(`/tasks/${task.id}`, { priority: e.target.value }, "PATCH"))}
          className="rounded-lg border border-edge bg-background px-2 py-1 text-xs"
        >
          {["low", "medium", "high", "critical"].map((p) => <option key={p} value={p}>priority: {p}</option>)}
        </select>
        <select
          value={task.assigned_agent_id ?? ""}
          onChange={(e) => act(() => post(`/tasks/${task.id}`, { assigned_agent_id: Number(e.target.value) }, "PATCH"))}
          className="rounded-lg border border-edge bg-background px-2 py-1 text-xs"
        >
          <option value="" disabled>reassign…</option>
          {agents.filter((a) => a.role !== "coordinator").map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
        </select>
        {task.status === "blocked" && (
          <button onClick={() => act(() => post(`/tasks/${task.id}`, { status: "in_progress", actor: "human", reason: "unblocked from dashboard" }, "PATCH"))}
            className="rounded-lg bg-sky-600 px-3 py-1 text-xs font-semibold text-white">Unblock</button>
        )}
        {task.status === "waiting_approval" && (
          <>
            <button onClick={() => act(() => post(`/tasks/${task.id}/approve`, { decided_by: "you", reason: "approved from dashboard" }))}
              className="rounded-lg bg-emerald-600 px-3 py-1 text-xs font-semibold text-white">Approve</button>
            <button onClick={() => act(() => post(`/tasks/${task.id}/reject`, { decided_by: "you", reason: "rejected from dashboard" }))}
              className="rounded-lg bg-red-600 px-3 py-1 text-xs font-semibold text-white">Reject</button>
          </>
        )}
        {!["completed", "cancelled"].includes(task.status) && (
          <button onClick={() => act(() => post(`/tasks/${task.id}/cancel`, {}))}
            className="rounded-lg border border-edge px-3 py-1 text-xs text-muted hover:text-foreground">Cancel</button>
        )}
      </div>
      {err && <p className="rounded-lg bg-red-500/10 p-2 text-xs text-red-300">{err.replace(/^Error: /, "")}</p>}

      {runs.length > 0 && (
        <div>
          <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted">Execution runs</h4>
          <ul className="space-y-1">
            {runs.map((r) => (
              <li key={r.id} className="rounded-lg border border-edge px-2 py-1.5 text-xs">
                <span className={r.status === "passed" ? "text-emerald-300" : "text-red-300"}>{r.status}</span>
                <span className="text-muted"> · {timeAgo(r.started_at)}</span>
                {r.output_summary && <pre className="mt-1 overflow-x-auto font-mono text-[10px] text-muted">{r.output_summary.slice(0, 400)}</pre>}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div>
        <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted">History</h4>
        <ul className="space-y-1 text-xs">
          {events.map((e) => (
            <li key={e.id} className="flex gap-2">
              <span className="text-muted">{timeAgo(e.created_at)}</span>
              <span>{e.event_type.replace("status:", "→ ")}</span>
              <span className="ml-auto text-muted">{e.actor}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

export default function Tasks() {
  const pid = useProjectId();
  const [selected, setSelected] = useState<number | null>(null);

  const load = useCallback(async () => {
    if (!pid) return null;
    const [tasks, agents] = await Promise.all([
      api<Task[]>(`/projects/${pid}/tasks`),
      api<Agent[]>(`/projects/${pid}/agents`),
    ]);
    return { tasks, agents };
  }, [pid]);
  const { data, reload } = useLive(load);

  if (!data) return <p className="text-muted">Loading…</p>;
  const { tasks, agents } = data;
  const sel = tasks.find((t) => t.id === selected) ?? null;
  const byAgent = (id: number | null) => agents.find((a) => a.id === id)?.role ?? "—";

  return (
    <div className="flex h-full gap-4">
      <div className="min-w-0 flex-1">
        <h1 className="mb-4 text-xl font-bold">Task Board</h1>
        <div className="flex gap-3 overflow-x-auto pb-4">
          {COLUMNS.map((col) => {
            const colTasks = tasks.filter((t) => t.status === col);
            return (
              <div key={col} className="w-60 shrink-0">
                <div className="mb-2 flex items-center justify-between px-1">
                  <Badge status={col} />
                  <span className="text-xs text-muted">{colTasks.length}</span>
                </div>
                <div className="space-y-2">
                  {colTasks.map((t) => (
                    <button key={t.id} onClick={() => setSelected(t.id)}
                      className={`w-full rounded-xl border bg-panel p-3 text-left transition-colors hover:border-accent ${
                        selected === t.id ? "border-accent" : "border-edge"}`}>
                      <div className="flex items-center gap-2 font-mono text-[11px] text-muted">
                        {t.key}
                        <span className={`h-1.5 w-1.5 rounded-full ${PRIORITY_DOT[t.priority] ?? ""}`} title={t.priority} />
                        {t.requires_approval && <span title="needs human approval">🔒</span>}
                        <span className="ml-auto">{byAgent(t.assigned_agent_id)}</span>
                      </div>
                      <div className="mt-1 line-clamp-2 text-sm">{t.title}</div>
                    </button>
                  ))}
                  {colTasks.length === 0 && <div className="rounded-xl border border-dashed border-edge p-3 text-center text-xs text-muted">empty</div>}
                </div>
              </div>
            );
          })}
        </div>
        {tasks.length === 0 && (
          <Panel><p className="text-sm text-muted">No tasks yet — send a request from Team Chat.</p></Panel>
        )}
      </div>
      {sel && <Detail task={sel} agents={agents} tasks={tasks} onClose={() => setSelected(null)} onChanged={reload} />}
    </div>
  );
}

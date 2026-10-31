"use client";

import { ErrorBox, Panel } from "@/components/ui";
import { Agent, AGENT_STATUS_CLS, api, Task, timeAgo, useLive, useProjectId } from "@/lib/api";
import { useCallback } from "react";

export default function Agents() {
  const pid = useProjectId();
  const load = useCallback(async () => {
    if (!pid) return null;
    const [agents, tasks] = await Promise.all([
      api<Agent[]>(`/projects/${pid}/agents`),
      api<Task[]>(`/projects/${pid}/tasks`),
    ]);
    return { agents, tasks };
  }, [pid]);
  const { data, error } = useLive(load);
  if (error) return <ErrorBox error={error} />;
  if (!data) return <p className="text-muted">Loading…</p>;

  const { agents, tasks } = data;
  const of = (a: Agent) => tasks.filter((t) => t.assigned_agent_id === a.id);

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">Agent Monitor</h1>
      <p className="text-sm text-muted">
        Status comes from real runtime signals (cards received, Switch liveness) — an agent that has
        never spoken shows <span className="text-zinc-400">offline</span>, not a fake green light.
      </p>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {agents.map((a) => {
          const mine = of(a);
          const current = mine.find((t) => ["in_progress", "in_review"].includes(t.status));
          return (
            <Panel key={a.id} title={a.name}
              right={<span className={`text-xs font-semibold capitalize ${AGENT_STATUS_CLS[a.status] ?? ""}`}>● {a.status}</span>}>
              <dl className="space-y-1.5 text-sm">
                <div className="flex justify-between"><dt className="text-muted">Role</dt><dd className="capitalize">{a.role}</dd></div>
                <div className="flex justify-between"><dt className="text-muted">Runtime</dt><dd>{a.runtime_type}</dd></div>
                <div className="flex justify-between"><dt className="text-muted">Current task</dt>
                  <dd className="truncate pl-2">{current ? `${current.key} ${current.title}` : "—"}</dd></div>
                <div className="flex justify-between"><dt className="text-muted">Completed</dt>
                  <dd>{mine.filter((t) => t.status === "completed").length}</dd></div>
                <div className="flex justify-between"><dt className="text-muted">Blocked</dt>
                  <dd>{mine.filter((t) => t.status === "blocked").length}</dd></div>
                <div className="flex justify-between"><dt className="text-muted">Last activity</dt><dd>{timeAgo(a.last_seen_at)}</dd></div>
              </dl>
            </Panel>
          );
        })}
      </div>
    </div>
  );
}

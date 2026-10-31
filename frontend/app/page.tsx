"use client";

import { Badge, ErrorBox, Panel } from "@/components/ui";
import {
  Agent, AGENT_STATUS_CLS, api, Metrics, Task, TaskEvent, timeAgo, useLive, useProjectId,
} from "@/lib/api";
import { useCallback } from "react";

type Data = { metrics: Metrics; agents: Agent[]; activity: TaskEvent[]; tasks: Task[] };

export default function Overview() {
  const pid = useProjectId();
  const load = useCallback(async (): Promise<Data | null> => {
    if (!pid) return null;
    const [metrics, agents, activity, tasks] = await Promise.all([
      api<Metrics>(`/projects/${pid}/metrics`),
      api<Agent[]>(`/projects/${pid}/agents`),
      api<TaskEvent[]>(`/projects/${pid}/activity?limit=12`),
      api<Task[]>(`/projects/${pid}/tasks`),
    ]);
    return { metrics, agents, activity, tasks };
  }, [pid]);
  const { data, error } = useLive(load);
  if (error) return <ErrorBox error={error} />;
  if (!data) return <p className="text-muted">Loading…</p>;

  const { metrics: m, agents, activity, tasks } = data;
  const taskKey = (id: number) => tasks.find((t) => t.id === id)?.key ?? `T-${id}`;
  const cards = [
    ["Total tasks", m.total_tasks], ["Completed", m.completed], ["In progress", m.in_progress],
    ["Blocked", m.blocked], ["Pending approvals", m.pending_approvals], ["Active agents", m.active_agents],
  ] as const;

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold">Overview</h1>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {cards.map(([label, value]) => (
          <div key={label} className="rounded-xl border border-edge bg-panel p-4">
            <div className="text-2xl font-bold">{value}</div>
            <div className="mt-1 text-xs text-muted">{label}</div>
          </div>
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Agents">
          <ul className="space-y-2">
            {agents.map((a) => (
              <li key={a.id} className="flex items-center justify-between rounded-lg border border-edge px-3 py-2">
                <div>
                  <div className="text-sm font-medium">{a.name}</div>
                  <div className="text-xs text-muted">{a.role} · {a.runtime_type}</div>
                </div>
                <div className="text-right">
                  <div className={`text-sm font-medium capitalize ${AGENT_STATUS_CLS[a.status] ?? ""}`}>{a.status}</div>
                  <div className="text-xs text-muted">seen {timeAgo(a.last_seen_at)}</div>
                </div>
              </li>
            ))}
          </ul>
        </Panel>

        <Panel title="Recent activity">
          {activity.length === 0 && <p className="text-sm text-muted">Nothing yet. Send a request in Team Chat.</p>}
          <ul className="space-y-1.5">
            {activity.map((e) => (
              <li key={e.id} className="flex items-baseline gap-2 text-sm">
                <span className="shrink-0 font-mono text-xs text-muted">{taskKey(e.task_id)}</span>
                <span className="truncate">{e.event_type.replace("status:", "→ ")}</span>
                <span className="ml-auto shrink-0 text-xs text-muted">{e.actor} · {timeAgo(e.created_at)}</span>
              </li>
            ))}
          </ul>
        </Panel>
      </div>

      <Panel title="Attention needed">
        {tasks.filter((t) => ["blocked", "waiting_approval", "failed"].includes(t.status)).length === 0 ? (
          <p className="text-sm text-muted">Nothing blocked and nothing waiting on you.</p>
        ) : (
          <ul className="space-y-2">
            {tasks.filter((t) => ["blocked", "waiting_approval", "failed"].includes(t.status)).map((t) => (
              <li key={t.id} className="flex items-center gap-3 rounded-lg border border-edge px-3 py-2 text-sm">
                <span className="font-mono text-xs text-muted">{t.key}</span>
                <span className="truncate">{t.title}</span>
                <span className="ml-auto"><Badge status={t.status} /></span>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}

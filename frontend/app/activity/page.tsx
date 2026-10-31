"use client";

import { ErrorBox, Panel } from "@/components/ui";
import { api, Task, TaskEvent, timeAgo, useLive, useProjectId } from "@/lib/api";
import { useCallback } from "react";

const ICON: Record<string, string> = {
  created: "✨", dispatched: "📨", status_update: "📝", test_result: "🧪",
  review_feedback: "👀", agent_reported_done: "📣", approval_requested: "🔔",
  approval_approved: "✅", approval_rejected: "🙅", blocker: "🧱",
  reassigned: "🔁", priority_changed: "⚖️", transition_refused: "⚠️",
};

export default function Activity() {
  const pid = useProjectId();
  const load = useCallback(async () => {
    if (!pid) return null;
    const [events, tasks] = await Promise.all([
      api<TaskEvent[]>(`/projects/${pid}/activity?limit=200`),
      api<Task[]>(`/projects/${pid}/tasks`),
    ]);
    return { events, tasks };
  }, [pid]);
  const { data, error } = useLive(load);
  if (error) return <ErrorBox error={error} />;
  if (!data) return <p className="text-muted">Loading…</p>;

  const key = (id: number) => data.tasks.find((t) => t.id === id)?.key ?? `T-${id}`;

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">Activity</h1>
      <Panel>
        {data.events.length === 0 && <p className="text-sm text-muted">No events yet.</p>}
        <ul className="space-y-1">
          {data.events.map((e) => {
            const icon = ICON[e.event_type] ?? (e.event_type.startsWith("status:") ? "➡️" : "·");
            const detail =
              (e.event_data.reason as string) || (e.event_data.message as string) ||
              (e.event_data.to ? `→ ${e.event_data.to}` : "") ||
              (typeof e.event_data.passed === "boolean" ? (e.event_data.passed ? "passed" : "failed") : "");
            return (
              <li key={e.id} className="flex items-baseline gap-2 border-b border-edge/40 py-1.5 text-sm last:border-0">
                <span className="w-5 text-center">{icon}</span>
                <span className="font-mono text-xs text-muted">{key(e.task_id)}</span>
                <span>{e.event_type.replace("status:", "status → ")}</span>
                {detail && <span className="truncate text-xs text-muted">{String(detail).slice(0, 80)}</span>}
                <span className="ml-auto shrink-0 text-xs text-muted">{e.actor} · {timeAgo(e.created_at)}</span>
              </li>
            );
          })}
        </ul>
      </Panel>
    </div>
  );
}

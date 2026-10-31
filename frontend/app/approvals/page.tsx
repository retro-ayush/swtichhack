"use client";

import { ErrorBox, Panel } from "@/components/ui";
import { api, Approval, post, Task, timeAgo, useLive, useProjectId } from "@/lib/api";
import { useCallback, useState } from "react";

export default function Approvals() {
  const pid = useProjectId();
  const [reason, setReason] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    if (!pid) return null;
    const [approvals, tasks] = await Promise.all([
      api<Approval[]>(`/projects/${pid}/approvals`),
      api<Task[]>(`/projects/${pid}/tasks`),
    ]);
    return { approvals, tasks };
  }, [pid]);
  const { data, reload, error } = useLive(load);
  if (error) return <ErrorBox error={error} />;
  if (!data) return <p className="text-muted">Loading…</p>;

  const { approvals, tasks } = data;
  const task = (id: number) => tasks.find((t) => t.id === id);
  const pending = approvals.filter((a) => a.status === "pending");
  const decided = approvals.filter((a) => a.status !== "pending");

  const decide = async (a: Approval, approve: boolean) => {
    setErr("");
    try {
      await post(`/tasks/${a.task_id}/${approve ? "approve" : "reject"}`,
        { decided_by: "you", reason: reason || (approve ? "approved" : "rejected") });
      setReason("");
      reload();
    } catch (e) { setErr(String(e)); }
  };

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold">Approvals</h1>
      <Panel title={`Pending (${pending.length})`}>
        {pending.length === 0 && <p className="text-sm text-muted">Nothing waiting on a human right now.</p>}
        <ul className="space-y-3">
          {pending.map((a) => {
            const t = task(a.task_id);
            return (
              <li key={a.id} className="rounded-xl border border-violet-500/30 bg-violet-500/5 p-4">
                <div className="text-sm font-semibold">{t?.key} — {t?.title}</div>
                <div className="mt-1 text-xs text-muted">requested by {a.requested_by} · {timeAgo(a.created_at)}</div>
                <div className="mt-3 flex items-center gap-2">
                  <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="decision reason (recorded in the audit log)"
                    className="flex-1 rounded-lg border border-edge bg-background px-3 py-1.5 text-xs outline-none focus:border-accent" />
                  <button onClick={() => decide(a, true)} className="rounded-lg bg-emerald-600 px-4 py-1.5 text-xs font-semibold text-white">Approve</button>
                  <button onClick={() => decide(a, false)} className="rounded-lg bg-red-600 px-4 py-1.5 text-xs font-semibold text-white">Reject</button>
                </div>
              </li>
            );
          })}
        </ul>
        {err && <p className="mt-2 rounded-lg bg-red-500/10 p-2 text-xs text-red-300">{err.replace(/^Error: /, "")}</p>}
      </Panel>

      <Panel title="Decision history">
        {decided.length === 0 && <p className="text-sm text-muted">No decisions yet.</p>}
        <ul className="space-y-1.5 text-sm">
          {decided.map((a) => (
            <li key={a.id} className="flex items-center gap-2">
              <span className="font-mono text-xs text-muted">{task(a.task_id)?.key}</span>
              <span className={a.status === "approved" ? "text-emerald-300" : "text-red-300"}>{a.status}</span>
              <span className="text-muted">by {a.approved_by}</span>
              {a.decision_reason && <span className="truncate text-xs text-muted">— {a.decision_reason}</span>}
              <span className="ml-auto text-xs text-muted">{a.decided_at ? timeAgo(a.decided_at) : ""}</span>
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  );
}

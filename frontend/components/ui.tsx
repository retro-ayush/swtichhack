"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { api, STATUS_META, SwitchStatus, useLive } from "@/lib/api";
import { useCallback } from "react";

export function Badge({ status }: { status: string }) {
  const m = STATUS_META[status] ?? { label: status, cls: "bg-slate-500/15 text-slate-300", dot: "bg-slate-400" };
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${m.cls}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${m.dot}`} />
      {m.label}
    </span>
  );
}

export function ViaBadge({ via }: { via: string }) {
  return via === "switch" ? (
    <span className="rounded bg-emerald-500/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-300">switch</span>
  ) : (
    <span className="rounded bg-zinc-500/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-zinc-400">local</span>
  );
}

export function ErrorBox({ error }: { error: string }) {
  return (
    <div className="rounded-xl border border-red-500/30 bg-red-500/5 p-4 text-sm">
      <div className="font-semibold text-red-300">Backend unreachable</div>
      <p className="mt-1 text-muted">
        {error.replace(/^Error: /, "")}. Start it with{" "}
        <code className="rounded bg-background px-1 font-mono text-xs">uvicorn app.main:app --port 8000</code>{" "}
        in <code className="font-mono text-xs">backend/</code>; this page reconnects automatically.
      </p>
    </div>
  );
}

export function Panel({ title, children, right }: {
  title?: string; children: React.ReactNode; right?: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-edge bg-panel">
      {title && (
        <header className="flex items-center justify-between border-b border-edge px-4 py-2.5">
          <h2 className="text-sm font-semibold text-foreground">{title}</h2>
          {right}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

function SwitchPill() {
  const load = useCallback(() => api<SwitchStatus>("/switch/status"), []);
  const { data } = useLive(load);
  const state = data?.state ?? "…";
  const color = state === "connected" ? "bg-emerald-400" : state === "disabled" ? "bg-zinc-500" : "bg-amber-400";
  return (
    <div className="flex items-center gap-2 rounded-lg border border-edge bg-background px-3 py-2 text-xs text-muted">
      <span className={`h-2 w-2 rounded-full ${color}`} />
      <span>Switch: {state}</span>
    </div>
  );
}

const NAV = [
  { href: "/", label: "Overview", icon: "▦" },
  { href: "/chat", label: "Team Chat", icon: "💬" },
  { href: "/tasks", label: "Tasks", icon: "☰" },
  { href: "/agents", label: "Agents", icon: "🤖" },
  { href: "/approvals", label: "Approvals", icon: "✓" },
  { href: "/activity", label: "Activity", icon: "⚡" },
];

export function Sidebar() {
  const path = usePathname();
  return (
    <aside className="flex h-screen w-56 shrink-0 flex-col border-r border-edge bg-panel">
      <div className="flex items-center gap-2 px-4 py-4">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent font-bold text-white">T</div>
        <div>
          <div className="text-sm font-bold leading-4">TeamPilot AI</div>
          <div className="text-[11px] text-muted">humans + agents, one team</div>
        </div>
      </div>
      <nav className="flex-1 space-y-0.5 px-2 py-2">
        {NAV.map((n) => (
          <Link key={n.href} href={n.href}
            className={`flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors ${
              path === n.href ? "bg-accent/15 text-foreground" : "text-muted hover:bg-white/5 hover:text-foreground"
            }`}>
            <span className="w-4 text-center text-xs">{n.icon}</span>
            {n.label}
          </Link>
        ))}
      </nav>
      {/* extra bottom padding keeps the pill clear of Next's dev indicator */}
      <div className="px-3 pb-12 pt-3"><SwitchPill /></div>
    </aside>
  );
}

"use client";

import { ErrorBox, ViaBadge } from "@/components/ui";
import { api, Message, post, timeAgo, useLive, useProjectId } from "@/lib/api";
import { useCallback, useEffect, useRef, useState } from "react";

const SENDER_CLS: Record<string, string> = {
  human: "text-sky-300", coordinator: "text-violet-300", agent: "text-emerald-300", system: "text-zinc-400",
};

function Body({ m }: { m: Message }) {
  const fence = m.content.indexOf("```json");
  const text = fence >= 0 ? m.content.slice(0, fence).trim() : m.content;
  return (
    <div className="space-y-1.5">
      {text && <p className="whitespace-pre-wrap text-sm leading-relaxed">{text}</p>}
      {m.structured && (
        <pre className="overflow-x-auto rounded-lg border border-edge bg-background p-2.5 font-mono text-xs text-muted">
          {JSON.stringify(m.structured, null, 2)}
        </pre>
      )}
    </div>
  );
}

export default function Chat() {
  const pid = useProjectId();
  const [draft, setDraft] = useState("");
  const [asRequest, setAsRequest] = useState(true);
  const [sending, setSending] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);

  const load = useCallback(
    () => (pid ? api<Message[]>(`/projects/${pid}/messages`) : Promise.resolve(null)),
    [pid],
  );
  const { data: messages, reload, error } = useLive(load);

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth" }); }, [messages?.length]);

  async function send() {
    if (!pid || !draft.trim() || sending) return;
    setSending(true);
    try {
      await post(`/projects/${pid}/chat`, { content: draft.trim(), sender_name: "you", as_request: asRequest });
      setDraft("");
      reload();
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <h1 className="mb-4 text-xl font-bold">Team Chat</h1>
      <div className="flex-1 space-y-3 overflow-y-auto rounded-xl border border-edge bg-panel p-4">
        {error && <ErrorBox error={error} />}
        {!error && !messages?.length && (
          <p className="text-sm text-muted">
            No messages yet. Try: “Investigate the login validation bug, fix it, and verify the solution.”
          </p>
        )}
        {messages?.map((m) => (
          <div key={m.id} className="rounded-lg border border-edge/60 bg-background/40 px-3 py-2">
            <div className="mb-1 flex items-center gap-2 text-xs">
              <span className={`font-semibold ${SENDER_CLS[m.sender_type] ?? ""}`}>{m.sender_name}</span>
              <span className="text-muted">{m.sender_type}</span>
              {m.message_type !== "CHAT" && (
                <span className="rounded bg-accent/15 px-1.5 py-0.5 font-mono text-[10px] text-indigo-300">{m.message_type}</span>
              )}
              <ViaBadge via={m.delivered_via} />
              <span className="ml-auto text-muted">{timeAgo(m.created_at)}</span>
            </div>
            <Body m={m} />
          </div>
        ))}
        <div ref={bottom} />
      </div>

      <div className="mt-3 rounded-xl border border-edge bg-panel p-3">
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
          rows={2}
          placeholder="Message the team… (Enter to send)"
          className="w-full resize-none rounded-lg border border-edge bg-background px-3 py-2 text-sm outline-none placeholder:text-muted focus:border-accent"
        />
        <div className="mt-2 flex items-center justify-between">
          <label className="flex items-center gap-2 text-xs text-muted">
            <input type="checkbox" checked={asRequest} onChange={(e) => setAsRequest(e.target.checked)} />
            Ask the coordinator to plan tasks from this message
          </label>
          <button
            onClick={send}
            disabled={sending || !draft.trim()}
            className="rounded-lg bg-accent px-4 py-1.5 text-sm font-semibold text-white disabled:opacity-40"
          >
            {sending ? "Sending…" : asRequest ? "Send request" : "Send"}
          </button>
        </div>
      </div>
    </div>
  );
}

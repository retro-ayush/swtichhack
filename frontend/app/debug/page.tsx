"use client";

import { useEffect, useState } from "react";

const PATHS = [
  "/projects", "/projects/1/metrics", "/projects/1/tasks", "/projects/1/agents",
  "/projects/1/activity?limit=12", "/projects/1/approvals", "/projects/1/messages",
];

/** Diagnostic page: fetches every dashboard endpoint from the browser and
 * prints status / size / error. Not linked from the sidebar. */
export default function Debug() {
  const [rows, setRows] = useState<string[]>([]);
  useEffect(() => {
    (async () => {
      const out: string[] = [];
      for (const p of PATHS) {
        const t0 = performance.now();
        try {
          const r = await fetch(`/api${p}`, { cache: "no-store" });
          const text = await r.text();
          let parsed = "parse-ok";
          try { JSON.parse(text); } catch (e) { parsed = `JSON ERROR ${String(e)}`; }
          out.push(`${p} -> ${r.status} ${text.length}B ${Math.round(performance.now() - t0)}ms ${parsed}`);
        } catch (e) {
          out.push(`${p} -> FETCH ERROR ${String(e)}`);
        }
        setRows([...out]);
      }
      out.push("DONE");
      setRows([...out]);
    })();
  }, []);
  return <pre id="debug-out" className="text-xs">{rows.join("\n") || "starting…"}</pre>;
}

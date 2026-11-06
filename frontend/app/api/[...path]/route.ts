// Server-side proxy to the TeamPilot backend.
// Adds TEAMPILOT_API_TOKEN on the server so the token never reaches the
// browser, and streams responses through unbuffered (needed for /api/stream SSE).

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";
const TOKEN = process.env.TEAMPILOT_API_TOKEN ?? "";

async function proxy(req: Request, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  const url = new URL(req.url);
  const target = `${BACKEND}/api/${path.map(encodeURIComponent).join("/")}${url.search}`;

  const headers = new Headers();
  const ct = req.headers.get("content-type");
  if (ct) headers.set("content-type", ct);
  const accept = req.headers.get("accept");
  if (accept) headers.set("accept", accept);
  if (TOKEN) headers.set("authorization", `Bearer ${TOKEN}`);

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: req.method,
      headers,
      body: req.method === "GET" || req.method === "HEAD" ? undefined : await req.text(),
      cache: "no-store",
      signal: req.signal,
    });
  } catch {
    return Response.json({ detail: `backend unreachable at ${BACKEND}` }, { status: 502 });
  }

  const out = new Headers();
  for (const h of ["content-type", "cache-control"]) {
    const v = upstream.headers.get(h);
    if (v) out.set(h, v);
  }
  out.set("x-accel-buffering", "no");
  return new Response(upstream.body, { status: upstream.status, headers: out });
}

export { proxy as GET, proxy as POST, proxy as PATCH, proxy as PUT, proxy as DELETE };

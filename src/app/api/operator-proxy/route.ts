import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = (
  process.env.API_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  process.env.VITE_API_BASE_URL ||
  "https://hive-production-7343.up.railway.app"
).replace(/\/$/, "");

const ALLOWED_POST_PREFIXES = [
  "/api/fast-training/",
  "/api/cycle/run",
  "/api/settings/clear-ghost-rows",
  "/api/strategies/import",
  "/api/settings/resync-broker-truth",
];

function pathAllowed(path: string): boolean {
  return ALLOWED_POST_PREFIXES.some((p) => path === p || path.startsWith(p));
}

export async function GET() {
  return NextResponse.json({
    status: "ok",
    server_operator_auth_configured: Boolean(process.env.OPERATOR_SECRET?.trim()),
    message: process.env.OPERATOR_SECRET?.trim()
      ? "Server-side operator proxy is configured (secret not exposed to browser)."
      : "Set OPERATOR_SECRET on the frontend service for server-side mutating proxy.",
  });
}

export async function POST(req: NextRequest) {
  const secret = (process.env.OPERATOR_SECRET || "").trim();
  if (!secret) {
    return NextResponse.json(
      {
        status: "blocked",
        message: "Operator proxy not configured on frontend service.",
      },
      { status: 503 }
    );
  }
  let payload: { path?: string; body?: unknown };
  try {
    payload = await req.json();
  } catch {
    return NextResponse.json({ status: "error", message: "Invalid JSON body" }, { status: 400 });
  }
  const path = String(payload.path || "").trim();
  if (!path.startsWith("/api/") || !pathAllowed(path)) {
    return NextResponse.json({ status: "forbidden", message: "Path not allowed via operator proxy" }, { status: 403 });
  }
  const url = `${BACKEND_URL}${path}`;
  const res = await fetch(url, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-Operator-Token": secret,
    },
    body: JSON.stringify(payload.body ?? {}),
    cache: "no-store",
  });
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { raw: text.slice(0, 500) };
  }
  return NextResponse.json(data, { status: res.status });
}

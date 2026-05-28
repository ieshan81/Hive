import { NextResponse } from "next/server";

const BACKEND =
  process.env.API_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  "https://hive-production-7343.up.railway.app";
const FALLBACK_BACKEND = "https://hive-production-7343.up.railway.app";

/** Server proxy — avoids client 404 when rewrites lag; fast summary only. */
export async function GET(request: Request) {
  const details = new URL(request.url).searchParams.get("details") === "1";
  const path = details ? "/api/cockpit?details=true" : "/api/cockpit";
  try {
    const primary = BACKEND.replace(/\/$/, "");
    let res = await fetch(`${primary}${path}`, {
      cache: "no-store",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(details ? 12000 : 8000),
    });
    if (res.status === 404 && primary !== FALLBACK_BACKEND) {
      res = await fetch(`${FALLBACK_BACKEND}${path}`, {
        cache: "no-store",
        headers: { Accept: "application/json" },
        signal: AbortSignal.timeout(details ? 12000 : 8000),
      });
    }
    const text = await res.text();
    return new NextResponse(text, {
      status: res.status,
      headers: { "Content-Type": res.headers.get("content-type") || "application/json" },
    });
  } catch (e) {
    const msg = e instanceof Error ? e.message : "Cockpit proxy failed";
    return NextResponse.json({ status: "error", message: msg }, { status: 502 });
  }
}

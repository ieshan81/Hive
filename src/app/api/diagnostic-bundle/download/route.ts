import { NextResponse } from "next/server";

export const maxDuration = 300;

const BACKEND_URL = (
  process.env.API_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  process.env.VITE_API_BASE_URL ||
  "https://hive-production-7343.up.railway.app"
).replace(/\/$/, "");

/** Long-running diagnostic zip proxy — avoids default rewrite timeout. */
export async function GET() {
  try {
    const res = await fetch(`${BACKEND_URL}/api/diagnostic-bundle/download?mode=latest`, {
      method: "GET",
      cache: "no-store",
    });
    if (!res.ok) {
      const text = await res.text();
      return NextResponse.json(
        {
          status: "error",
          message: `Backend diagnostic download failed (${res.status})`,
          detail: text.slice(0, 300),
        },
        { status: res.status }
      );
    }
    const blob = await res.arrayBuffer();
    return new NextResponse(blob, {
      status: 200,
      headers: {
        "Content-Type": "application/zip",
        "Content-Disposition": "attachment; filename=hive-diagnostic-bundle.zip",
      },
    });
  } catch (err) {
    return NextResponse.json(
      {
        status: "error",
        message: err instanceof Error ? err.message : "Diagnostic download proxy failed",
      },
      { status: 502 }
    );
  }
}

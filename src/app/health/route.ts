/** Railway healthcheck — must not depend on backend availability during deploy. */
export async function GET() {
  return Response.json({ status: "ok", service: "hive-frontend" });
}

import { redirect } from "next/navigation";

/** Push-pull strategy UI merged into Mission Control; backend logic unchanged. */
export default function PushPullPage() {
  redirect("/mission-control");
}

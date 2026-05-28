import { redirect } from "next/navigation";

/** Push-pull strategy UI merged into Cockpit; backend logic unchanged. */
export default function PushPullPage() {
  redirect("/cockpit");
}

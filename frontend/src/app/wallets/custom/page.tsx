import { redirect } from "next/navigation";

export default function CustomWalletsRedirect() {
  redirect("/dashboard");
}

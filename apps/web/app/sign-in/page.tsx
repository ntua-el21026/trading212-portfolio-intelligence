import { redirect } from "next/navigation";

import { SignInPanel } from "../../components/sign-in-panel";
import { getWebAccess } from "../../lib/auth";
import { isExplicitDemoMode, isLocalApiAuthEnabled } from "../../lib/runtime";

export const dynamic = "force-dynamic";

export default async function SignInPage() {
  if (await getWebAccess()) {
    redirect("/");
  }
  return (
    <SignInPanel
      demoEnabled={isExplicitDemoMode()}
      localApiAuthEnabled={isLocalApiAuthEnabled()}
    />
  );
}

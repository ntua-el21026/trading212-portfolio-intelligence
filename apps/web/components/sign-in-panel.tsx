import { ArrowRight, LockKeyhole, ShieldCheck } from "lucide-react";
import Link from "next/link";

export function SignInPanel({
  demoEnabled,
  localApiAuthEnabled = false,
}: Readonly<{ demoEnabled: boolean; localApiAuthEnabled?: boolean }>) {
  return (
    <main className="sign-in-page">
      <section className="sign-in-card" aria-labelledby="sign-in-heading">
        <Link className="brand sign-in-brand" href="/sign-in">
          Portfolio Intelligence
        </Link>
        <div className="sign-in-intro">
          <span className="sign-in-icon">
            <ShieldCheck aria-hidden="true" size={26} strokeWidth={1.6} />
          </span>
          <h1 id="sign-in-heading">Private portfolio access</h1>
          <p>
            Review canonical portfolio history, holdings, and data quality
            through a strictly read-only interface.
          </p>
        </div>
        {demoEnabled || localApiAuthEnabled ? (
          <form
            action={
              demoEnabled ? "/api/auth/demo-session" : "/api/auth/local-session"
            }
            method="post"
          >
            <button className="sign-in-action" type="submit">
              {demoEnabled ? "Enter demo portfolio" : "Start local session"}
              <ArrowRight aria-hidden="true" size={18} />
            </button>
            <p className="sign-in-note">
              {demoEnabled
                ? "Local synthetic data only. No Trading 212 credentials or broker requests are used."
                : "The local API issues a short-lived HttpOnly session. Broker credentials never reach the browser."}
            </p>
          </form>
        ) : (
          <div className="sign-in-disabled" role="status">
            <strong>Authentication is not configured</strong>
            <p>
              Access fails closed until the deployment authentication adapter is
              available.
            </p>
          </div>
        )}
        <div className="read-only-callout">
          <LockKeyhole aria-hidden="true" size={19} />
          <span>
            <strong>Read-only by design</strong>
            This application cannot place, amend, or cancel trades.
          </span>
        </div>
      </section>
    </main>
  );
}

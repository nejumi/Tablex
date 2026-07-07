import React from "react";
import { KeyRound, Loader2 } from "lucide-react";
import type { LocaleMessages } from "../copy";

type AuthGateStatus = {
  bootstrap_required: boolean;
  google_auth_enabled: boolean;
};

export function AuthGate({
  status,
  text,
  error,
  onSubmit
}: {
  status: AuthGateStatus;
  text: LocaleMessages;
  error: string | null;
  onSubmit: (email: string, password: string, displayName: string | null) => Promise<void>;
}) {
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [displayName, setDisplayName] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [localError, setLocalError] = React.useState<string | null>(null);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setLocalError(null);
    try {
      await onSubmit(email.trim(), password, displayName.trim() || null);
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-shell">
      <section className="auth-card">
        <div className="auth-brand">
          <img src="/mascot/tablee-success.svg" alt="" aria-hidden="true" />
          <div>
            <span>Tablex</span>
            <h1>{text.signInTitle}</h1>
            <p>{text.signInBody}</p>
          </div>
        </div>
        {error || localError ? <div className="banner danger">{localError ?? error}</div> : null}
        <form className="auth-form" onSubmit={(event) => void submit(event)}>
          <label>
            <span>{text.email}</span>
            <input
              autoComplete="email"
              autoFocus
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
          </label>
          {status.bootstrap_required ? (
            <label>
              <span>{text.displayName}</span>
              <input autoComplete="name" value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
            </label>
          ) : null}
          <label>
            <span>{text.password}</span>
            <input
              autoComplete={status.bootstrap_required ? "new-password" : "current-password"}
              minLength={10}
              pattern="(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{10,}"
              title={text.passwordRequirement}
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
            <small>{text.passwordRequirement}</small>
          </label>
          <button className="primary-button" disabled={busy || !email.trim() || !password} type="submit">
            {busy ? <Loader2 className="spin" size={16} /> : <KeyRound size={16} />}
            {status.bootstrap_required ? text.createFirstUser : text.signIn}
          </button>
        </form>
        <div className="auth-provider-row">
          <span className="badge">{text.passwordAuth}</span>
          {status.google_auth_enabled ? <span className="badge muted">Google</span> : <small>{text.googleAuthComingSoon}</small>}
        </div>
      </section>
    </main>
  );
}

import { useState } from "react";
import { api } from "../api.js";

// The slug the P5 migration seeds the single tenant with. Prefilling it keeps
// the existing single-tenant operator's login a two-field affair, while the
// field itself is what makes the form usable by a second tenant whose users may
// share an email address with the first.
const DEFAULT_TENANT = "default";

export default function Login({ onLogin }) {
  const [tenant, setTenant] = useState(DEFAULT_TENANT);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.login(tenant, email, password);
      onLogin();
    } catch {
      setError("Wrong tenant, email or password.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="center">
      <form className="card login" onSubmit={submit}>
        <h1>QA Portal</h1>
        <p className="muted">Sign in to administer the E2E test flow.</p>
        <input
          type="text"
          placeholder="Tenant"
          value={tenant}
          onChange={(e) => setTenant(e.target.value)}
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck="false"
        />
        <input
          type="email"
          placeholder="Email"
          value={email}
          autoFocus
          onChange={(e) => setEmail(e.target.value)}
        />
        <input
          type="password"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {error && <div className="error">{error}</div>}
        <button className="btn primary" disabled={busy || !tenant || !email || !password}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}

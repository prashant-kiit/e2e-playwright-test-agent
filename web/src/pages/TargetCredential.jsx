import { useEffect, useState } from "react";
import { api } from "../api.js";

// A target's GitHub credential: the customer's own PAT, not the operator's.
//
// Through P4 there was one `GITHUB_PAT` in the API's environment, so every
// delivery into every customer's repository was authored by the same identity.
// This panel is where that becomes the customer's own credential. Three things
// about it are deliberate.
//
// The token is **write-only**. It goes up once, is sealed on the target's row
// (ciphertext in Postgres, data key wrapped by a KMS key) and never comes back:
// there is no field on the response that could carry it, so there is nothing
// here to render it into and nothing for a browser's network log to keep. The
// input is cleared on a successful save for the same reason.
//
// The **scope check happens at save time**, server-side, against GitHub. A
// token missing `workflow` would otherwise fail hours later inside a delivery,
// where the message reaches whoever is reading the run rather than whoever
// pasted the token. A 422 here lands in the form that caused it.
//
// The **warning is the point of the panel**, more than the form is. An expiry
// nobody is told about is a delivery that stops working on a Tuesday for no
// visible reason, so `warning` is rendered above everything else and the
// expiring, absent and rejected cases each say what to do about them.

export default function TargetCredential({ target, onChange }) {
  const [status, setStatus] = useState(null);
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    api
      .targetCredential(target.id)
      .then((s) => live && setStatus(s))
      .catch(() => live && setStatus(null));
    return () => {
      live = false;
    };
  }, [target.id]);

  function applied(next, message) {
    setStatus(next);
    setToken("");
    setNotice(message);
    setError("");
    onChange?.();
  }

  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const next = await api.saveTargetPat(target.id, token.trim());
      applied(
        next,
        next.login
          ? `Saved. Deliveries to ${target.target_repo} will be authored by ${next.login}.`
          : "Saved.",
      );
    } catch (e) {
      // 422 is "this token will not do", which is the operator's to fix and
      // belongs beside the field. Anything else is reported as it arrives.
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  async function clear() {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      applied(await api.clearTargetPat(target.id), "Token removed.");
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  if (!status) return <section className="card">Loading…</section>;

  const stored = status.state !== "absent";

  return (
    <section className="card target-credential">
      <div className="page-head">
        <h2>GitHub credential</h2>
      </div>

      {/* `warning` is only ever set when something needs doing, so it is never
          styled as a success -- a lapsing expiry rendered green was the first
          version of this and read as reassurance. `invalid` is the one case
          where delivery is already broken rather than about to be. */}
      {status.warning && (
        <div className={status.state === "invalid" ? "error" : "banner"}>
          {status.warning}
        </div>
      )}
      {error && <div className="error">{error}</div>}
      {notice && <div className="banner success">{notice}</div>}

      <dl className="kv">
        <dt>Status</dt>
        <dd>
          <span className={`pill ${stored ? "pill-completed" : "pill-pending"}`}>
            {status.state}
          </span>
        </dd>
        <dt>Expires</dt>
        <dd>
          {status.expires_at
            ? `${new Date(status.expires_at).toLocaleDateString()}${
                status.days_until_expiry !== null
                  ? ` (${status.days_until_expiry} days)`
                  : ""
              }`
            : "no expiry reported"}
        </dd>
      </dl>

      <form className="form-grid" onSubmit={save}>
        <label>
          Personal access token
          {/* type=password so a pasted credential is not readable over a
              shoulder or in a screen share, and autoComplete off so no browser
              offers to remember a customer's PAT. */}
          <input
            type="password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            autoComplete="off"
            placeholder="ghp_… or github_pat_…"
            required
          />
        </label>
        <p className="muted">
          Needs <code>repo</code> and <code>workflow</code> scope — delivery pushes a
          GitHub Actions workflow. The token is encrypted before it is stored and is
          never shown again, never sent to a test run, and never written to a log.
        </p>
        <div className="inline-form">
          <button className="btn primary" disabled={busy || !token.trim()}>
            {busy ? "Saving…" : stored ? "Replace token" : "Save token"}
          </button>
          {stored && (
            <button type="button" className="btn ghost" disabled={busy} onClick={clear}>
              Remove token
            </button>
          )}
        </div>
      </form>
    </section>
  );
}

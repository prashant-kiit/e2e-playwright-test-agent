// Small shared UI bits.

export function StatusPill({ status }) {
  return <span className={`pill pill-${status}`}>{status}</span>;
}

export function Spinner({ label = "Loading…" }) {
  return <div className="muted">{label}</div>;
}

export function Field({ label, children }) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
    </label>
  );
}

// A refused write, when the reason is a live run.
//
// It is not a failure the operator caused and it has a specific remedy, so it
// gets its own banner rather than the generic error area -- and both write
// surfaces (stories, configuration) say the same thing, because the server
// refuses them for the same reason.
export function LiveRunBanner({ detail }) {
  if (!detail) return null;
  return (
    <div className="banner banner-bad">
      <strong>Not saved — this target has a live run.</strong>
      <div>{detail}</div>
    </div>
  );
}

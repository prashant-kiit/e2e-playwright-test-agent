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

// This tenant's usage against its plan caps (P5-04).
//
// Two gauges, asked about independently, because both caps can be full at once
// and the server reports them as two flags for that reason. An unmetered cap
// (`null`, meaning no cap rather than a cap of zero) shows the count with no
// denominator: "2 runs this month" rather than "2 of 0".
//
// Shown where the runs are started, so an operator sees what is left *before*
// pressing Start rather than discovering it in a 429.
export function UsageMeter({ usage }) {
  if (!usage) return null;
  const gauges = [
    {
      key: "concurrency",
      label: "Running now",
      used: usage.live_runs,
      cap: usage.max_concurrent_runs,
      full: usage.at_concurrency_cap,
      // The remedy differs per cap, which is the whole reason they are
      // separate: one clears itself, the other does not.
      note: "at your concurrent-run cap — wait for a run to finish, or stop one",
    },
    {
      key: "monthly",
      label: "This month",
      used: usage.runs_this_month,
      cap: usage.monthly_run_quota,
      full: usage.at_monthly_quota,
      note: "out of runs for this calendar month — the quota resets on the 1st",
    },
  ];
  return (
    <div className="usage-meter">
      {gauges.map((g) => (
        <div key={g.key} className={`usage-gauge${g.full ? " usage-gauge-full" : ""}`}>
          <span className="usage-label">{g.label}</span>
          <span className="usage-count">
            {/* `== null` on purpose, catching undefined as well as null: a
                field the server stopped sending would otherwise render as
                "2 of undefined" rather than falling back to "no cap". */}
            {g.cap == null ? `${g.used}` : `${g.used} of ${g.cap}`}
          </span>
          {g.cap == null && <span className="usage-note muted">no cap</span>}
          {g.full && <span className="usage-note">{g.note}</span>}
        </div>
      ))}
    </div>
  );
}

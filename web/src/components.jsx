import { useEffect, useState } from "react";
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
export function UsageMeter({ usage, canEdit = false, onSave }) {
  // The caps the server last told us about. Seeded from the prop and then
  // owned here, because a save returns the stored values and those are what
  // the gauges must show -- the panel is not entitled to render what was
  // typed.
  const [stored, setStored] = useState(usage);
  const [editing, setEditing] = useState(false);
  useEffect(() => setStored(usage), [usage]);
  const shown = stored || usage;
  if (!shown) return null;
  const gauges = [
    {
      key: "concurrency",
      label: "Running now",
      used: shown.live_runs,
      cap: shown.max_concurrent_runs,
      full: shown.at_concurrency_cap,
      // The remedy differs per cap, which is the whole reason they are
      // separate: one clears itself, the other does not.
      note: "at your concurrent-run cap — wait for a run to finish, or stop one",
    },
    {
      key: "monthly",
      label: "This month",
      used: shown.runs_this_month,
      cap: shown.monthly_run_quota,
      full: shown.at_monthly_quota,
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
      {canEdit && !editing && (
        <button className="btn ghost" onClick={() => setEditing(true)}>
          Change caps
        </button>
      )}
      {canEdit && editing && (
        <CapsEditor
          caps={shown}
          onSave={onSave}
          onDone={(saved) => {
            if (saved) setStored(saved);
            setEditing(false);
          }}
        />
      )}
    </div>
  );
}

// The write half of the panel above (P5-13 / #45).
//
// Shown only to an admin, and that is presentation: the server's admin
// dependency is what enforces story 5, and a member who reached the route
// anyway is refused there. A hidden button is a tidier portal, not a
// permission -- which is why a refusal is rendered rather than treated as
// impossible.
//
// The editor's whole subtlety is in what it *sends*. Three states have to stay
// distinguishable, because the route treats them as three different requests:
//
//   untouched   not sent at all -- the stored cap is left alone
//   emptied     sent as `null` -- unmetered, a value an admin may choose
//   a number    sent as that number
//
// Collapsing the first two is how raising one cap silently deletes the other,
// which already happened once at `repo.set_tenant_caps` before it took an
// `UNSET` sentinel. So the fields start from the stored values and only those
// whose text actually changed are put in the body.
function CapsEditor({ caps, onSave, onDone }) {
  const fields = [
    { name: "max_concurrent_runs", label: "Concurrent runs" },
    { name: "monthly_run_quota", label: "Runs per month" },
  ];
  // `null` (unmetered) edits as an empty box, which is also how it is cleared.
  const asText = (value) => (value == null ? "" : String(value));
  const initial = Object.fromEntries(
    fields.map((f) => [f.name, asText(caps[f.name])]),
  );
  const [text, setText] = useState(initial);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  function body() {
    const out = {};
    for (const f of fields) {
      if (text[f.name] === initial[f.name]) continue; // untouched: not sent
      out[f.name] = text[f.name].trim() === "" ? null : Number(text[f.name]);
    }
    return out;
  }

  async function save() {
    const changes = body();
    if (Object.keys(changes).length === 0) {
      onDone(null); // nothing to say to the server
      return;
    }
    setSaving(true);
    setError("");
    try {
      onDone(await onSave(changes));
    } catch (e) {
      // Left open, so a refused save does not also discard what was typed.
      setError(String(e.message || e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="caps-editor">
      {fields.map((f) => (
        <label key={f.name} className="caps-field">
          {f.label}
          <input
            type="number"
            min="0"
            value={text[f.name]}
            placeholder="no cap"
            onChange={(e) => setText({ ...text, [f.name]: e.target.value })}
          />
        </label>
      ))}
      <span className="muted">Empty means no cap.</span>
      <button className="btn" disabled={saving} onClick={save}>
        Save
      </button>
      <button className="btn ghost" disabled={saving} onClick={() => onDone(null)}>
        Cancel
      </button>
      {error && <div className="banner banner-bad">{error}</div>}
    </div>
  );
}

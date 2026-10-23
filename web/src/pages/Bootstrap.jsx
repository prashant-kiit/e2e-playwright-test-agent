import { useState } from "react";
import { api } from "../api.js";
import { Field } from "../components.jsx";

const EMPTY = {
  app: "",
  name: "",
  baseURL: "",
  targetRepo: "",
  targetBranch: "master",
  locators: "",
};

export default function Bootstrap() {
  const [form, setForm] = useState(EMPTY);
  const [notes, setNotes] = useState("");
  const [doBootstrap, setDoBootstrap] = useState(true);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const body = {
        ...form,
        agentNotes: notes.split("\n").map((s) => s.trim()).filter(Boolean),
        do_bootstrap: doBootstrap,
      };
      setResult(await api.bootstrapApp(body));
      setForm(EMPTY);
      setNotes("");
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="page-head">
        <h1>Bootstrap a target app</h1>
      </div>
      <section className="card">
        <p className="muted">
          Creates <code>apps/&lt;app&gt;/</code> (app.json + seed) and, when enabled, runs the
          target-repo bootstrap. Add stories afterwards under <code>user-stories/</code>.
        </p>
        <form className="form-grid" onSubmit={submit}>
          <Field label="App folder (lower-case, hyphens)">
            <input value={form.app} onChange={set("app")} placeholder="my-app" required />
          </Field>
          <Field label="Display name">
            <input value={form.name} onChange={set("name")} placeholder="My App" required />
          </Field>
          <Field label="Base URL">
            <input value={form.baseURL} onChange={set("baseURL")} placeholder="https://my-app.example.com" />
          </Field>
          <Field label="Target repo (owner/repo)">
            <input value={form.targetRepo} onChange={set("targetRepo")} placeholder="owner/repo" />
          </Field>
          <Field label="Target branch">
            <input value={form.targetBranch} onChange={set("targetBranch")} />
          </Field>
          <Field label="Locator convention">
            <input value={form.locators} onChange={set("locators")} placeholder="data-testid attributes" />
          </Field>
          <Field label="Agent notes (one per line)">
            <textarea rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} />
          </Field>
          <label className="checkbox">
            <input type="checkbox" checked={doBootstrap} onChange={(e) => setDoBootstrap(e.target.checked)} />
            Run target-repo bootstrap now (needs GitHub access)
          </label>
          <button className="btn primary" disabled={busy || !form.app || !form.name}>
            {busy ? "Bootstrapping…" : "Create target"}
          </button>
        </form>
        {error && <div className="error">{error}</div>}
        {/* A failed target-repo sync is a partial outcome, not a success: the app
            folder exists but nothing reached GitHub. Plain `banner` reads amber,
            `banner success` green. */}
        {result && (
          <div className={result.bootstrap && !result.bootstrap.ok ? "banner" : "banner success"}>
            Created <code>apps/{result.app}</code>.
            {result.bootstrap
              ? result.bootstrap.ok
                ? " Target repo bootstrapped."
                : " Target-repo bootstrap failed — the app folder was still created."
              : " (target-repo bootstrap skipped)"}
            {result.bootstrap?.output && <pre className="log">{result.bootstrap.output}</pre>}
          </div>
        )}
      </section>
    </div>
  );
}

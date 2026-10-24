import { useEffect, useState } from "react";
import { api } from "../api.js";
import { Field, Spinner } from "../components.jsx";
import { ConfigFields, noteLines, useFields } from "../config-form.jsx";

// Register a target entirely in the portal.
//
// Onboarding an application no longer means committing to the harness's git
// repo: this writes the configuration row and commits revision 1 from the
// templates — the seed, the infra set and the generated Playwright config — so
// the target has a tree to hydrate and a history to show before its first run.
//
// The optional infra sync is the old bootstrap checkbox, unchanged: it pushes
// the infra entries to the target repo through delivery. A failure there is an
// outcome, not an error — the target exists either way.

const EMPTY = {
  app: "",
  name: "",
  base_url: "",
  target_repo: "",
  target_branch: "master",
  locators: "",
};

export default function NewTarget() {
  const [projects, setProjects] = useState(null);
  const [projectId, setProjectId] = useState("");
  const [form, set, setForm] = useFields(EMPTY);
  const [notes, setNotes] = useState("");
  const [syncInfra, setSyncInfra] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .listProjects()
      .then((p) => {
        setProjects(p);
        if (p.length) setProjectId(String(p[0].id));
      })
      .catch((e) => setError(String(e.message || e)));
  }, []);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setResult(null);
    try {
      setResult(
        await api.createTarget(Number(projectId), {
          ...form,
          agent_notes: noteLines(notes),
          sync_infra: syncInfra,
        }),
      );
      setForm(EMPTY);
      setNotes("");
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  if (projects === null && !error) return <Spinner />;

  return (
    <div>
      <div className="page-head">
        <h1>New target</h1>
      </div>
      <section className="card">
        <p className="muted">
          Writes the target&rsquo;s configuration and commits <strong>revision 1</strong> from the
          templates: the seed, the infra files and a Playwright config generated from the base URL
          below. Add stories afterwards from the target&rsquo;s Stories panel.
        </p>
        {projects !== null && projects.length === 0 && (
          <div className="banner">Create a project first — a target belongs to one.</div>
        )}
        <form className="form-grid" onSubmit={submit}>
          <Field label="Project">
            <select value={projectId} onChange={(e) => setProjectId(e.target.value)} required>
              {(projects || []).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Slug (lower-case, hyphens)">
            <input value={form.app} onChange={set("app")} placeholder="my-app" required />
          </Field>
          <Field label="Display name">
            <input value={form.name} onChange={set("name")} placeholder="My App" required />
          </Field>
          <ConfigFields form={form} set={set} notes={notes} setNotes={setNotes} />
          <label className="checkbox">
            <input type="checkbox" checked={syncInfra} onChange={(e) => setSyncInfra(e.target.checked)} />
            Also sync the infra files to the target repo now (needs GitHub access)
          </label>
          <button
            className="btn primary"
            disabled={busy || !projectId || !form.app || !form.name || !form.base_url || !form.target_repo}
          >
            {busy ? "Creating…" : "Create target"}
          </button>
        </form>
        {error && <div className="error">{error}</div>}
        {/* A failed infra sync is a partial outcome, not a success: the target
            and its revision 1 exist but nothing reached GitHub. Plain `banner`
            reads amber, `banner success` green. */}
        {result && (
          <div className={result.bootstrap && !result.bootstrap.ok ? "banner" : "banner success"}>
            Created <code>{result.target.app}</code> at revision {result.revision.rev} (
            {result.revision.file_count} files).
            {result.bootstrap
              ? result.bootstrap.ok
                ? " Infra synced to the target repo."
                : " The infra sync failed — the target was still created."
              : " (infra sync skipped)"}
            {result.bootstrap?.output && <pre className="log">{result.bootstrap.output}</pre>}
          </div>
        )}
      </section>
    </div>
  );
}

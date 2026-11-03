import { useEffect, useState } from "react";
import { api } from "../api.js";
import { Spinner } from "../components.jsx";

export default function Settings() {
  const [settings, setSettings] = useState(null);
  const [prompts, setPrompts] = useState([]);
  const [open, setOpen] = useState(null);
  const [error, setError] = useState("");
  // The open prompt's unsaved text, and what it was when editing began. The
  // draft is keyed by nothing: only one prompt is open at a time, so closing
  // one and opening another discards the draft, which is the behaviour the
  // single `open` already implied.
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");

  function openPrompt(p) {
    if (open === p.name) {
      setOpen(null);
      return;
    }
    setOpen(p.name);
    setDraft(p.content);
    setSaveError("");
  }

  async function savePrompt(name) {
    setSaving(true);
    setSaveError("");
    try {
      const saved = await api.savePrompt(name, draft);
      // Replace the row in place so the new revision shows without a reload.
      setPrompts((all) => all.map((p) => (p.name === name ? saved : p)));
      setDraft(saved.content);
    } catch (e) {
      setSaveError(String(e.message || e));
    } finally {
      setSaving(false);
    }
  }

  useEffect(() => {
    Promise.all([api.getSettings(), api.getPrompts()])
      .then(([s, p]) => {
        setSettings(s);
        setPrompts(p);
      })
      .catch((e) => setError(String(e.message || e)));
  }, []);

  if (error) return <div className="error">{error}</div>;
  if (!settings) return <Spinner />;

  return (
    <div>
      <div className="page-head">
        <h1>Settings</h1>
      </div>

      <section className="card">
        <h2>Runtime (read-only)</h2>
        <dl className="kv">
          <dt>Agent runner</dt>
          <dd>
            <code>{settings.runner}</code>{" "}
            {settings.runner === "fake" && <span className="muted">(no tokens)</span>}
          </dd>
          <dt>Claude model</dt>
          <dd>
            <code>{settings.model}</code>
          </dd>
          <dt>Anthropic API key</dt>
          <dd>{settings.anthropic_api_key_set ? "configured" : "not set"}</dd>
          <dt>Runs dir</dt>
          <dd className="mono">{settings.runs_dir}</dd>
          <dt>Worktrees dir</dt>
          <dd className="mono">{settings.worktrees_dir}</dd>
        </dl>
        <p className="muted">
          These come from the backend environment (QA_RUNNER, ANTHROPIC_MODEL, …). Editing from
          the UI is a later milestone.
        </p>
        <p className="muted">
          There is no repo root. A target&rsquo;s configuration and its tree live in Postgres and
          blob storage; the two directories above are per-run scratch — a worktree is built from
          the head revision before a run and deleted after it.
        </p>
      </section>

      <section className="card">
        <h2>Prompts</h2>
        <p className="muted">
          These are the instructions the agent is sent, and they are yours to tune — an edit
          here applies to your tenant alone and takes effect on your next run, with no
          redeploy. Revision 1 is the default this harness ships; saving a change records a
          new revision rather than overwriting the old one, so the history is kept.
        </p>
        <div className="prompt-list">
          {prompts.map((p) => (
            <div key={p.name} className="prompt">
              <button className="prompt-head" onClick={() => openPrompt(p)}>
                <span className="mono">{p.name}</span>
                <span className="muted">
                  {p.rev > 1 ? `edited · rev ${p.rev}` : "default"}
                  {" · "}
                  {open === p.name ? "hide" : "edit"}
                </span>
              </button>
              {open === p.name && (
                <div className="prompt-edit">
                  <textarea
                    className="log prompt-body"
                    rows={20}
                    value={draft}
                    spellCheck={false}
                    onChange={(e) => setDraft(e.target.value)}
                  />
                  {saveError && <div className="error">{saveError}</div>}
                  <div className="row-actions">
                    <button
                      className="primary"
                      disabled={saving || draft === p.content}
                      onClick={() => savePrompt(p.name)}
                    >
                      {saving ? "Saving…" : `Save as revision ${p.rev + 1}`}
                    </button>
                    <button
                      disabled={saving || draft === p.content}
                      onClick={() => setDraft(p.content)}
                    >
                      Discard changes
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

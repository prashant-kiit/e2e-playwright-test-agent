import { useEffect, useState } from "react";
import { api } from "../api.js";
import { Spinner } from "../components.jsx";

export default function Settings() {
  const [settings, setSettings] = useState(null);
  const [prompts, setPrompts] = useState([]);
  const [open, setOpen] = useState(null);
  const [error, setError] = useState("");

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
          <dt>Repo root</dt>
          <dd className="mono">{settings.repo_root}</dd>
          <dt>Runs dir</dt>
          <dd className="mono">{settings.runs_dir}</dd>
        </dl>
        <p className="muted">
          These come from the backend environment (QA_RUNNER, ANTHROPIC_MODEL, …). Editing from
          the UI is a later milestone.
        </p>
      </section>

      <section className="card">
        <h2>Prompts (read-only)</h2>
        <div className="prompt-list">
          {prompts.map((p) => (
            <div key={p.name} className="prompt">
              <button className="prompt-head" onClick={() => setOpen(open === p.name ? null : p.name)}>
                <span className="mono">{p.name}</span>
                <span className="muted">{open === p.name ? "hide" : "view"}</span>
              </button>
              {open === p.name && <pre className="log">{p.content}</pre>}
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

import { useEffect, useState } from "react";
import { api } from "../api.js";
import { Spinner } from "../components.jsx";
import { lineDiff } from "../diff.js";
import Users from "./Users.jsx";

/** How to label when a revision was saved -- a time, or the words "shipped
 * default", which is why this is a label and not a date. `null` for a
 * shipped default that is not yet a
 * row: there is no moment at which those bytes became this tenant's, and a
 * date invented for them would be a wrong answer in the one panel whose job
 * is to say when things changed (see `prompt_store.PromptRevision`). */
function savedLabel(createdAt) {
  if (!createdAt) return "shipped default";
  return new Date(createdAt).toLocaleString();
}

/** One revision's content: a diff against the revision before it, or -- for
 * the first -- the body itself, because there is nothing to compare it to. */
function RevisionDetail({ revision, previous }) {
  if (!previous) {
    return (
      <pre className="log prompt-revision-body" data-testid="prompt-revision-body">
        {revision.content}
      </pre>
    );
  }
  const diff = lineDiff(previous.content, revision.content);
  return (
    <pre className="log prompt-diff" data-testid="prompt-diff">
      {diff.map((line, i) => (
        <div key={i} className={`diff-${line.kind}`}>
          {line.kind === "added" ? "+ " : line.kind === "removed" ? "- " : "  "}
          {line.text}
        </div>
      ))}
    </pre>
  );
}

/**
 * A prompt's revision history (#39), with a diff per revision.
 *
 * Loaded on demand and kept in this component rather than in `Settings`: the
 * history of one prompt is nobody else's state, and hoisting it would mean
 * `Settings` holding a map keyed by prompt name for the one prompt that can be
 * open at a time.
 *
 * Revisions are listed **newest first** although the API answers oldest first.
 * The rows come back in rev order because that is the order they are in, and
 * "what did I change last" is the question a customer opens this with -- but
 * the diff still compares against the *previous* revision, so each entry
 * answers "what did this edit change".
 */
function PromptHistory({ name }) {
  const [revisions, setRevisions] = useState(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(null);

  useEffect(() => {
    let live = true;
    setRevisions(null);
    setError("");
    setOpen(null);
    api
      .getPromptHistory(name)
      // Oldest first on the wire; a copy reversed for display, so the index
      // arithmetic for "the revision before this one" stays on the original
      // order.
      .then((h) => live && setRevisions(h))
      // Reported, never swallowed. A panel that degrades to nothing is how
      // P5-04's quota gauges shipped invisible with their tests passing.
      .catch((e) => live && setError(String(e.message || e)));
    return () => {
      live = false;
    };
  }, [name]);

  if (error) return <div className="error">{error}</div>;
  if (!revisions) return <Spinner />;

  return (
    <div className="prompt-history">
      {revisions.length === 1 && (
        <p className="muted">
          This prompt has never been edited — what follows is the default this
          harness ships.
        </p>
      )}
      {revisions
        .map((revision, i) => ({ revision, previous: revisions[i - 1] }))
        .reverse()
        .map(({ revision, previous }) => (
          <div
            className="prompt-revision"
            data-testid="prompt-revision"
            key={revision.rev}
          >
            <button
              className="prompt-revision-head"
              onClick={() => setOpen(open === revision.rev ? null : revision.rev)}
            >
              <span>rev {revision.rev}</span>
              <span className="muted">
                {savedLabel(revision.created_at)}
                {" · "}
                {open === revision.rev ? "hide" : previous ? "what changed" : "view"}
              </span>
            </button>
            {open === revision.rev && (
              <RevisionDetail revision={revision} previous={previous} />
            )}
          </div>
        ))}
    </div>
  );
}

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
  // Whether the open prompt's history is showing. One flag rather than a set:
  // only one prompt is open at a time, and `openPrompt` closes the history
  // with it.
  const [showHistory, setShowHistory] = useState(false);
  // Whether to render the user-administration panel. Presentation only: the
  // server's admin dependency is what enforces it, and the panel itself
  // renders a refusal if it is ever shown to somebody who cannot use it.
  const [isAdmin, setIsAdmin] = useState(false);

  function openPrompt(p) {
    if (open === p.name) {
      setOpen(null);
      return;
    }
    setOpen(p.name);
    setDraft(p.content);
    setSaveError("");
    setShowHistory(false);
  }

  async function savePrompt(name) {
    setSaving(true);
    setSaveError("");
    try {
      const saved = await api.savePrompt(name, draft);
      // Replace the row in place so the new revision shows without a reload.
      setPrompts((all) => all.map((p) => (p.name === name ? saved : p)));
      setDraft(saved.content);
      // The history now has a revision the panel has not seen. Closing it is
      // honest and costs one click; leaving it open would show a list missing
      // the edit that was just made.
      setShowHistory(false);
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
    // Separately and quietly: not knowing the role hides a panel, which is
    // not a reason to fail the page the operator came to for prompts.
    api
      .me()
      .then((who) => setIsAdmin(who.role === "admin"))
      .catch(() => setIsAdmin(false));
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

      {isAdmin && (
        <section className="card">
          <h2>Users</h2>
          <p className="muted">
            Everyone who can sign in to your tenant. Inviting someone creates their
            account and shows a password <em>once</em> — there is no mail from this
            portal, so copy it and pass it on; nothing here can recover it afterwards.
            Admins can approve deliveries, rotate credentials, change quotas and
            administer users; members cannot. A tenant cannot be left without an admin.
          </p>
          <Users />
        </section>
      )}

      <section className="card">
        <h2>Prompts</h2>
        <p className="muted">
          These are the instructions the agent is sent, and they are yours to tune — an edit
          here applies to your tenant alone and takes effect on your next run, with no
          redeploy. Revision 1 is the default this harness ships; saving a change records a
          new revision rather than overwriting the old one, so the history is kept —
          open a prompt and choose <em>History</em> to see what each edit changed and
          when it was saved.
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
                    <button onClick={() => setShowHistory((on) => !on)}>
                      {showHistory ? "Hide history" : "History"}
                    </button>
                  </div>
                  {showHistory && <PromptHistory name={p.name} />}
                </div>
              )}
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

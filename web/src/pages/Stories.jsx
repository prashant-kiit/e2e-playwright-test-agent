import { useEffect, useState } from "react";
import { api } from "../api.js";
import { Field, Spinner } from "../components.jsx";

// The story editor for one target.
//
// With the repo mount gone this is the only way a story gets in. Every write
// commits one revision authored by the operator, so who changed what and when
// is answerable from the same history that records the agent's work.
//
// A write while the target has a live run is refused with a 409, not queued.
// The run hydrated from an older head, and its next ingest would commit a tree
// without the edit -- silently reverting it. There is no merge logic anywhere
// in this system, so the portal says why rather than pretending to queue.

const TEMPLATE = (storyId) =>
  `# User Story: ${storyId} - <title>\n\n` +
  `As a <role>, I want <capability>, so that <benefit>.\n\n` +
  `## Acceptance criteria\n\n` +
  `1. ...\n`;

function slugify(text) {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export default function Stories({ target, onRevision }) {
  const [stories, setStories] = useState(null);
  const [editing, setEditing] = useState(null); // { story_id, slug, content, isNew }
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    setStories(await api.listStories(target.id));
  }

  useEffect(() => {
    load().catch((e) => setError(String(e.message || e)));
  }, [target.id]);

  function report(e) {
    // A 409 is not a failure the operator caused; it has a specific remedy, so
    // it gets its own banner and the generic error area stays empty.
    if (e.status === 409) {
      setConflict(String(e.message || e));
      setError("");
    } else {
      setError(String(e.message || e));
      setConflict("");
    }
  }

  async function save() {
    setBusy(true);
    setError("");
    setConflict("");
    setNotice("");
    try {
      const slug = editing.slug.trim() || slugify(editing.story_id);
      const out = await api.writeStory(target.id, editing.story_id, {
        story_id: editing.story_id,
        slug,
        content: editing.content,
      });
      setStories(out.stories);
      setNotice(
        out.revision
          ? `Saved as revision ${out.revision.rev}.`
          : "No change — the story is already exactly this, so no revision was committed.",
      );
      setEditing(null);
      onRevision?.();
    } catch (e) {
      report(e);
    } finally {
      setBusy(false);
    }
  }

  async function remove(storyId) {
    setBusy(true);
    setError("");
    setConflict("");
    setNotice("");
    try {
      const out = await api.deleteStory(target.id, storyId);
      setStories(out.stories);
      setNotice(
        `Deleted ${storyId} as revision ${out.revision.rev}. Its plan and test suite were left in place.`,
      );
      onRevision?.();
    } catch (e) {
      report(e);
    } finally {
      setBusy(false);
    }
  }

  async function open(storyId) {
    setError("");
    setConflict("");
    try {
      const story = await api.readStory(target.id, storyId);
      setEditing({ ...story, isNew: false });
    } catch (e) {
      report(e);
    }
  }

  function startNew() {
    setNotice("");
    setEditing({ story_id: "", slug: "", content: "", isNew: true });
  }

  if (error && stories === null) return <div className="error">{error}</div>;
  if (stories === null) return <Spinner label="Loading stories…" />;

  return (
    <section className="card stories">
      <div className="page-head">
        <h2>User stories</h2>
        <button className="btn" onClick={startNew} disabled={busy}>
          New story
        </button>
      </div>

      {conflict && (
        <div className="banner banner-bad">
          <strong>Not saved — this target has a live run.</strong>
          <div>{conflict}</div>
        </div>
      )}
      {error && <div className="error">{error}</div>}
      {notice && <div className="banner">{notice}</div>}

      {stories.length === 0 ? (
        <p className="muted">
          No stories yet. Write one here — it is committed as a revision, and a run can start
          from it straight away.
        </p>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>Story</th>
              <th>Title</th>
              <th>File</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {stories.map((s) => (
              <tr key={s.story_id}>
                <td>
                  <code>{s.story_id}</code>
                </td>
                <td>{s.title}</td>
                <td className="muted mono">{s.file}</td>
                <td className="row-actions">
                  <button className="btn ghost sm" onClick={() => open(s.story_id)} disabled={busy}>
                    Edit
                  </button>
                  <button
                    className="btn ghost sm danger"
                    onClick={() => remove(s.story_id)}
                    disabled={busy}
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {editing && (
        <form
          className="form-grid story-editor"
          onSubmit={(e) => {
            e.preventDefault();
            save();
          }}
        >
          <h3>{editing.isNew ? "New story" : `Editing ${editing.story_id}`}</h3>
          <Field label="Story ID (e.g. SCRUM-201)">
            <input
              value={editing.story_id}
              onChange={(e) => setEditing({ ...editing, story_id: e.target.value })}
              placeholder="SCRUM-201"
              readOnly={!editing.isNew}
              required
            />
          </Field>
          <Field label="Slug (becomes the file name and the test folder)">
            <input
              value={editing.slug}
              onChange={(e) => setEditing({ ...editing, slug: e.target.value })}
              placeholder="auth"
              required
            />
          </Field>
          <Field label="Story (markdown)">
            <textarea
              rows={14}
              className="mono"
              value={editing.content}
              onChange={(e) => setEditing({ ...editing, content: e.target.value })}
              required
            />
          </Field>
          <div className="row-actions">
            <button className="btn primary" disabled={busy || !editing.story_id || !editing.content}>
              {busy ? "Saving…" : "Save as a revision"}
            </button>
            <button type="button" className="btn ghost" onClick={() => setEditing(null)}>
              Cancel
            </button>
            {editing.isNew && (
              <button
                type="button"
                className="btn ghost sm"
                onClick={() =>
                  setEditing({
                    ...editing,
                    slug: editing.slug || slugify(editing.story_id),
                    content: TEMPLATE(editing.story_id || "SCRUM-000"),
                  })
                }
              >
                Insert template
              </button>
            )}
          </div>
        </form>
      )}
    </section>
  );
}

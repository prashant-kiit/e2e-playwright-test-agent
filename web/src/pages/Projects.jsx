import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api.js";
import { Spinner } from "../components.jsx";
import Revisions from "./Revisions.jsx";
import Stories from "./Stories.jsx";
import TargetConfig from "./TargetConfig.jsx";

// Projects and their targets.
//
// A target is one row: its configuration, its stories and its tree all live in
// the database, so everything on this page reads one concept. The portal used
// to show a filesystem-backed "app" list alongside the target rows, which were
// two names for the same thing; P3 collapsed them.

export default function Projects() {
  const [projects, setProjects] = useState(null);
  const [targets, setTargets] = useState([]);
  const [newProject, setNewProject] = useState("");
  const [error, setError] = useState("");

  async function load() {
    const [p, t] = await Promise.all([api.listProjects(), api.listTargets()]);
    setProjects(p);
    setTargets(t);
  }
  useEffect(() => {
    load().catch((e) => setError(String(e.message || e)));
  }, []);

  async function addProject(e) {
    e.preventDefault();
    try {
      await api.createProject(newProject.trim());
      setNewProject("");
      load();
    } catch (e) {
      setError(String(e.message || e));
    }
  }

  if (projects === null) return <Spinner />;

  return (
    <div>
      <div className="page-head">
        <h1>Projects &amp; Targets</h1>
        <form className="inline-form" onSubmit={addProject}>
          <input
            placeholder="New project name"
            value={newProject}
            onChange={(e) => setNewProject(e.target.value)}
          />
          <button className="btn primary" disabled={!newProject.trim()}>
            Add project
          </button>
        </form>
      </div>
      {error && <div className="error">{error}</div>}
      {projects.length === 0 && <p className="muted">No projects yet. Create one above.</p>}
      {projects.map((p) => (
        <ProjectCard
          key={p.id}
          project={p}
          targets={targets.filter((t) => t.project_id === p.id)}
          onChange={load}
        />
      ))}
    </div>
  );
}

function ProjectCard({ project, targets, onChange }) {
  const navigate = useNavigate();
  return (
    <section className="card">
      <h2>{project.name}</h2>
      <div className="targets">
        {targets.length === 0 && <p className="muted">No targets yet.</p>}
        {targets.map((t) => (
          <TargetRow key={t.id} target={t} onChange={onChange} />
        ))}
      </div>
      <button className="btn" onClick={() => navigate("/targets/new")}>
        Add target
      </button>
    </section>
  );
}

// Which panel of a target is open. One at a time: they are three views of the
// same tree and showing all three at once buries the one being read.
const PANELS = ["stories", "config", "revisions"];

function TargetRow({ target, onChange }) {
  const navigate = useNavigate();
  const [story, setStory] = useState("");
  const [stories, setStories] = useState([]);
  const [mode, setMode] = useState("full");
  const [delivery, setDelivery] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [panel, setPanel] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);

  async function loadStories() {
    const s = await api.listStories(target.id);
    setStories(s);
    if (s.length && !s.some((x) => x.story_id === story)) setStory(s[0].story_id);
  }

  useEffect(() => {
    loadStories().catch(() => setStories([]));
    // The delivery state is one Postgres query, so it is cheap to show inline
    // and needs no network call to GitHub.
    api.deliveryState(target.id).then(setDelivery).catch(() => setDelivery(null));
  }, [target.id, reloadKey]);

  async function start(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const run = await api.startRun(target.id, story.trim(), mode);
      navigate(`/runs/${run.id}`);
    } catch (e) {
      // 409 must not be an operator's first hint that runs aren't queued: say
      // so, since there is no queue to fall back on (DESIGN.md §5).
      setError(
        e.status === 409
          ? "This target already has a live run. Runs are not queued — wait for it to finish, or pause/stop it, then start this one."
          : String(e.message || e),
      );
    } finally {
      setBusy(false);
    }
  }

  function afterWrite() {
    setReloadKey((k) => k + 1);
    onChange?.();
  }

  return (
    <div className="target-row">
      <div className="target-meta">
        <strong>{target.name}</strong>
        <span className="row-sub">
          <code>{target.app}</code>
          <a
            href={`https://github.com/${target.target_repo}`}
            target="_blank"
            rel="noreferrer"
            className="code-link"
          >
            View target code ↗
          </a>
          <DeliveryBadge state={delivery} />
          {PANELS.map((name) => (
            <button
              key={name}
              className="btn ghost sm"
              onClick={() => setPanel(panel === name ? null : name)}
            >
              {panel === name ? `Hide ${name}` : name[0].toUpperCase() + name.slice(1)}
            </button>
          ))}
        </span>
      </div>
      <form className="inline-form" onSubmit={start}>
        {stories.length > 0 ? (
          <select value={story} onChange={(e) => setStory(e.target.value)} title="User story">
            {stories.map((s) => (
              <option key={s.story_id} value={s.story_id}>
                {s.story_id} — {s.title}
              </option>
            ))}
          </select>
        ) : (
          <span className="muted">No stories yet — write one in the Stories panel.</span>
        )}
        <select value={mode} onChange={(e) => setMode(e.target.value)} title="Test mode">
          <option value="full">Full app</option>
          <option value="changed">Changed only</option>
        </select>
        <button className="btn primary" disabled={busy || !story.trim()}>
          {busy ? "Starting…" : "Start QA run"}
        </button>
      </form>
      {error && <div className="error">{error}</div>}
      {panel === "stories" && (
        <div className="target-panel">
          <Stories target={target} onRevision={afterWrite} />
        </div>
      )}
      {panel === "config" && (
        <div className="target-panel">
          <TargetConfig target={target} onSaved={afterWrite} />
        </div>
      )}
      {panel === "revisions" && (
        <div className="target-panel">
          <Revisions target={target} key={reloadKey} />
        </div>
      )}
    </div>
  );
}

// "Delivered" or "N revisions ahead" — one query, no network call to GitHub, so
// the answer is the same for everyone and does not depend on reachability.
function DeliveryBadge({ state }) {
  if (!state) return null;
  if (state.delivered) {
    return (
      <span className="pill pill-completed" title={`Commit ${state.delivered_sha}`}>
        delivered
      </span>
    );
  }
  return (
    <span className="pill pill-pending" title={state.summary}>
      {state.revisions_ahead} rev{state.revisions_ahead === 1 ? "" : "s"} ahead
    </span>
  );
}

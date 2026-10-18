import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api.js";
import { Spinner } from "../components.jsx";

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
  const [app, setApp] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");

  async function addTarget(e) {
    e.preventDefault();
    try {
      await api.createTarget(project.id, app.trim(), name.trim());
      setApp("");
      setName("");
      onChange();
    } catch (e) {
      setError(String(e.message || e));
    }
  }

  return (
    <section className="card">
      <h2>{project.name}</h2>
      <div className="targets">
        {targets.length === 0 && <p className="muted">No targets yet.</p>}
        {targets.map((t) => (
          <TargetRow key={t.id} target={t} />
        ))}
      </div>
      <form className="inline-form target-add" onSubmit={addTarget}>
        <input
          placeholder="app folder (e.g. practice-target)"
          value={app}
          onChange={(e) => setApp(e.target.value)}
        />
        <input placeholder="display name" value={name} onChange={(e) => setName(e.target.value)} />
        <button className="btn" disabled={!app.trim() || !name.trim()}>
          Add target
        </button>
      </form>
      {error && <div className="error">{error}</div>}
    </section>
  );
}

function TargetRow({ target }) {
  const navigate = useNavigate();
  const [story, setStory] = useState("");
  const [mode, setMode] = useState("full");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function start(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const run = await api.startRun(target.id, story.trim(), mode);
      navigate(`/runs/${run.id}`);
    } catch (e) {
      setError(e.status === 409 ? "This app already has a live run." : String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="target-row">
      <div className="target-meta">
        <strong>{target.name}</strong>
        <code>{target.app}</code>
      </div>
      <form className="inline-form" onSubmit={start}>
        <input
          placeholder="story (e.g. SCRUM-201)"
          value={story}
          onChange={(e) => setStory(e.target.value)}
        />
        <select value={mode} onChange={(e) => setMode(e.target.value)} title="Test mode">
          <option value="full">Full app</option>
          <option value="changed">Changed only</option>
        </select>
        <button className="btn primary" disabled={busy || !story.trim()}>
          {busy ? "Starting…" : "Start QA run"}
        </button>
      </form>
      {error && <div className="error">{error}</div>}
    </div>
  );
}

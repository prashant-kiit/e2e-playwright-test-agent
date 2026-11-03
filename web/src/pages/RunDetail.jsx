import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api.js";
import { Spinner, StatusPill } from "../components.jsx";

const STEP_ORDER = ["read_story", "plan", "explore", "generate", "heal"];
const LIVE = new Set(["pending", "running", "paused"]);

export default function RunDetail() {
  const { id } = useParams();
  const [run, setRun] = useState(null);
  const [steps, setSteps] = useState([]);
  const [artifacts, setArtifacts] = useState([]);
  const [log, setLog] = useState([]);
  const [error, setError] = useState("");
  const logRef = useRef(null);

  async function refetch() {
    const [r, s, a] = await Promise.all([
      api.getRun(id),
      api.runSteps(id),
      api.runArtifacts(id),
    ]);
    setRun(r);
    setSteps(s);
    setArtifacts(a);
    return r;
  }

  // Initial load + live log stream.
  //
  // The stream needs its own session handling: `EventSource` opens its own
  // connection, so `api.js`'s refresh-on-401 never sees it, and per spec it
  // does *not* reconnect after an HTTP error status -- it fires `error` once
  // and stays shut. With a 15-minute access cookie that would leave the log
  // pane silently and permanently empty (the status beside it keeps polling),
  // so a failed connection renews the session and reopens once.
  useEffect(() => {
    let es = null;
    let done = false; // the effect has been torn down, or the run has ended
    let retried = false;

    function open() {
      es = new EventSource(`/runs/${id}/events`, { withCredentials: true });
      es.onmessage = (ev) => {
        // A line delivered means the connection works, which earns the stream
        // a fresh retry: a long run can outlive more than one expiry.
        retried = false;
        try {
          setLog((l) => [...l, JSON.parse(ev.data)]);
        } catch {
          setLog((l) => [...l, ev.data]);
        }
      };
      es.addEventListener("end", () => {
        done = true;
        es.close();
        refetch().catch(() => {});
      });
      es.onerror = async () => {
        es.close();
        // `retried` bounds this: a stream that fails again without having
        // delivered anything is failing for a reason no cookie can fix, and
        // reopening on that would spin.
        if (done || retried) return;
        retried = true;
        if (await api.renewSession()) {
          if (!done) open();
        }
      };
    }

    refetch().catch((e) => setError(String(e.message || e)));
    open();
    return () => {
      done = true;
      es?.close();
    };
  }, [id]);

  // Poll run/steps while the run is live (SSE covers the log).
  useEffect(() => {
    if (!run || !LIVE.has(run.status)) return;
    const t = setInterval(() => {
      refetch().catch(() => {});
    }, 2000);
    return () => clearInterval(t);
  }, [run?.status]);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [log]);

  async function control(fn) {
    try {
      await fn(id);
      await refetch();
    } catch (e) {
      setError(String(e.message || e));
    }
  }

  if (error) return <div className="error">{error}</div>;
  if (!run) return <Spinner />;

  const live = LIVE.has(run.status);
  const stepStatus = Object.fromEntries(steps.map((s) => [s.step, s.status]));

  return (
    <div className="run-detail">
      <div className="page-head">
        <div>
          <h1>
            {run.story_id} <StatusPill status={run.status} />
          </h1>
          <div className="muted mono">{run.run_key}</div>
        </div>
        <div className="controls">
          <button
            className="btn"
            disabled={run.status !== "running"}
            onClick={() => control(api.pauseRun)}
          >
            Pause
          </button>
          <button
            className="btn"
            disabled={run.status !== "paused"}
            onClick={() => control(api.resumeRun)}
          >
            Resume
          </button>
          <button
            className="btn danger"
            disabled={!live}
            onClick={() => control(api.stopRun)}
          >
            Stop
          </button>
        </div>
      </div>

      {run.pause_requested && run.status === "running" && (
        <div className="banner">Pausing — will stop after the current step.</div>
      )}
      {run.error && <div className="error">Error: {run.error}</div>}

      <section className="card">
        <h2>Pipeline</h2>
        <ol className="steps">
          {STEP_ORDER.map((name, i) => {
            const st = stepStatus[name] || (run.current_step === name ? "running" : "pending");
            const active = run.current_step === name;
            return (
              <li key={name} className={`step step-${st} ${active ? "active" : ""}`}>
                <span className="step-num">{i + 1}</span>
                <span className="step-name">{name}</span>
                <span className="step-state">{st}</span>
              </li>
            );
          })}
        </ol>
      </section>

      <section className="card">
        <h2>Live log</h2>
        <pre className="log" ref={logRef}>
          {log.length === 0 ? "(no output yet)" : log.join("\n")}
        </pre>
      </section>

      <section className="card">
        <h2>Artifacts ({artifacts.length})</h2>
        {artifacts.length === 0 && <p className="muted">None yet.</p>}
        <div className="artifacts">
          {artifacts.map((a) => (
            <ArtifactCard key={a.id} art={a} />
          ))}
        </div>
      </section>
    </div>
  );
}

function ArtifactCard({ art }) {
  const url = api.artifactContentUrl(art.id);
  const name = art.s3_key.split("/").slice(1).join("/");
  return (
    <div className="artifact">
      <div className="artifact-head">
        <span className={`tag tag-${art.kind}`}>{art.kind}</span>
        <span className="muted">{art.step || "—"}</span>
        <span className="muted">v{art.version}</span>
      </div>
      {art.kind === "screenshot" ? (
        <a href={url} target="_blank" rel="noreferrer">
          <img className="thumb" src={url} alt={name} />
        </a>
      ) : null}
      <div className="artifact-name mono">{name}</div>
      <a className="btn ghost sm" href={url} target="_blank" rel="noreferrer">
        {art.kind === "report" ? "View" : "Download"}
      </a>
    </div>
  );
}

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { Spinner, StatusPill } from "../components.jsx";

export default function Runs() {
  const [runs, setRuns] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .listRuns()
      .then(setRuns)
      .catch((e) => setError(String(e.message || e)));
  }, []);

  if (error) return <div className="error">{error}</div>;
  if (runs === null) return <Spinner />;

  return (
    <div>
      <div className="page-head">
        <h1>Run History</h1>
      </div>
      {runs.length === 0 && <p className="muted">No runs yet.</p>}
      {runs.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Run</th>
              <th>Story</th>
              <th>Mode</th>
              <th>Status</th>
              <th>Last step</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.id}>
                <td>
                  <Link to={`/runs/${r.id}`}>{r.run_key}</Link>
                </td>
                <td>{r.story_id}</td>
                <td>{r.mode}</td>
                <td>
                  <StatusPill status={r.status} />
                </td>
                <td>{r.last_completed_step || "—"}</td>
                <td>{new Date(r.created_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

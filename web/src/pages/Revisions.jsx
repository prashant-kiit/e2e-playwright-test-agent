import { useEffect, useState } from "react";
import { api } from "../api.js";
import { Spinner } from "../components.jsx";

// The read-only Revisions panel for one target.
//
// The operator's window into the tree the database holds: the revision list,
// one revision's files, and one file's contents streamed out of blob storage.
// This is where the generated suite is read.
//
// Nothing here writes. The writers are a run's ingest, at each step boundary
// that changed something, and the operator's own story and config edits. There
// is no snapshot button: the filesystem is not authoritative, so "snapshot the
// disk" stopped meaning anything. There is no parity banner either -- with one
// copy of the truth left there is nothing to compare it against, and the
// property parity checked by comparison is now checked by construction
// (the materialize/re-scan round trip in the backend tests).

const SHORT_HASH = 12;

function short(hash) {
  return hash ? hash.slice(0, SHORT_HASH) : "—";
}

function humanSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function Revisions({ target }) {
  const [revisions, setRevisions] = useState(null);
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState("");

  async function load() {
    const revs = await api.listRevisions(target.id);
    setRevisions(revs);
    return revs;
  }

  useEffect(() => {
    load().catch((e) => setError(String(e.message || e)));
  }, [target.id]);

  if (error && revisions === null) return <div className="error">{error}</div>;
  if (revisions === null) return <Spinner label="Loading revisions…" />;

  const head = revisions[0];

  return (
    <section className="card revisions">
      <div className="page-head">
        <h2>
          Revisions
          {head ? (
            <span className="rev-head">
              {" "}
              — rev {head.rev}{" "}
              <code className="mono" title={head.tree_hash}>
                {short(head.tree_hash)}
              </code>
            </span>
          ) : null}
        </h2>
      </div>

      {error && <div className="error">{error}</div>}

      {revisions.length === 0 ? (
        <p className="muted">
          No revisions yet. A target created in the portal has revision 1 from the moment it
          exists, so an empty history here means this target predates that and cannot be run.
        </p>
      ) : (
        <>
          <table className="table">
            <thead>
              <tr>
                <th>Rev</th>
                <th>Parent</th>
                <th>Tree</th>
                <th>Author</th>
                <th>Run</th>
                <th>Files</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {revisions.map((r) => (
                <tr key={r.id} className={selected?.id === r.id ? "active" : ""}>
                  <td>
                    <button className="btn ghost sm" onClick={() => setSelected(r)}>
                      rev {r.rev}
                    </button>
                  </td>
                  <td className="muted">{r.parent_rev ?? "—"}</td>
                  <td>
                    <code className="mono" title={r.tree_hash}>
                      {short(r.tree_hash)}
                    </code>
                  </td>
                  <td className="muted">{r.author}</td>
                  <td className="muted">{r.produced_by_run_id ?? "—"}</td>
                  <td>{r.file_count}</td>
                  <td className="muted">{new Date(r.created_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {/* A run producing fewer revisions than steps reads like a bug
              unless the panel says why. */}
          <p className="muted hint">
            A run commits a revision only at the step boundaries that <strong>changed</strong>{" "}
            something: reading the story and exploring normally change nothing, so a five-step run
            usually leaves two or three revisions, not five. <code>operator</code> revisions are
            story and configuration edits made here.
          </p>
        </>
      )}

      {selected && <RevisionFiles revision={selected} />}
    </section>
  );
}

function RevisionFiles({ revision }) {
  const [files, setFiles] = useState(null);
  const [openPath, setOpenPath] = useState(null);
  const [contents, setContents] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setFiles(null);
    setOpenPath(null);
    setContents(null);
    setError("");
    api
      .revisionFiles(revision.id)
      .then(setFiles)
      .catch((e) => setError(String(e.message || e)));
  }, [revision.id]);

  async function open(path) {
    setOpenPath(path);
    setContents(null);
    setError("");
    try {
      // Byte-for-byte what the snapshot stored, served out of blob storage
      // rather than read off the shared disk. Never re-encode it: running a
      // tracked package.json through JSON.stringify would show the operator
      // reformatted text and call it the stored file.
      setContents(await api.revisionFile(revision.id, path));
    } catch (e) {
      setError(String(e.message || e));
    }
  }

  if (error && files === null) return <div className="error">{error}</div>;
  if (files === null) return <Spinner label="Loading files…" />;

  return (
    <div className="rev-files">
      <h2>
        Revision {revision.rev} — {files.length} files
      </h2>
      <div className="rev-files-split">
        <ul className="file-list">
          {files.map((f) => (
            <li key={f.path} className={openPath === f.path ? "active" : ""}>
              <button className="file-row" onClick={() => open(f.path)}>
                <span className="mono file-path">{f.path}</span>
                <span className="muted file-size">{humanSize(f.size)}</span>
              </button>
            </li>
          ))}
        </ul>
        <div className="file-view">
          {error && <div className="error">{error}</div>}
          {openPath === null && !error && (
            <p className="muted">Pick a file to read it out of blob storage.</p>
          )}
          {openPath !== null && contents === null && !error && <Spinner label="Fetching…" />}
          {contents !== null && (
            <>
              <div className="muted mono file-view-head">{openPath}</div>
              <pre className="log">{contents}</pre>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

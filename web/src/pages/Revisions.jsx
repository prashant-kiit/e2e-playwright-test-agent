import { useEffect, useState } from "react";
import { api } from "../api.js";
import { Spinner } from "../components.jsx";

// The read-only Revisions panel for one target (P2).
//
// Everything here reads the dual-written revision model: the parity banner, the
// revision list, one revision's files and one file's contents out of blob
// storage. Nothing on this panel writes a revision, a file index row or a blob
// -- that would let the portal make the database disagree with the authoritative
// filesystem, which is the one thing this phase must not do.
//
// The single exception is the snapshot button, which is P2-only scaffolding: it
// exists so a target that has never run still has a head revision to compare
// parity against. In P3 the filesystem is not authoritative and "snapshot the
// disk" stops meaning anything.

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
  const [parity, setParity] = useState(null);
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    const [revs, par] = await Promise.all([
      api.listRevisions(target.id),
      api.targetParity(target.id),
    ]);
    setRevisions(revs);
    setParity(par);
    return revs;
  }

  useEffect(() => {
    load().catch((e) => setError(String(e.message || e)));
  }, [target.id]);

  async function snapshot() {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const out = await api.snapshotTarget(target.id);
      setNotice(
        out.created
          ? `Snapshotted: revision ${out.revision.rev}.`
          : `No change — the tree still matches revision ${out.revision.rev}, so nothing was committed.`,
      );
      await load();
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

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
        <button className="btn" onClick={snapshot} disabled={busy}>
          {busy ? "Snapshotting…" : "Snapshot now"}
        </button>
      </div>

      <ParityBanner parity={parity} />
      {notice && <div className="banner">{notice}</div>}
      {error && <div className="error">{error}</div>}

      {revisions.length === 0 ? (
        <p className="muted">
          No revisions yet. Take a snapshot to give this target a head revision to compare
          against, or start a run — a run baselines the target before its first step.
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
          {/* Two revisions for what feels like one piece of work reads like an
              off-by-one unless the portal says why. */}
          <p className="muted hint">
            A target&rsquo;s first run leaves <strong>two revisions</strong>: the{" "}
            <code>baseline</code>, which is the tree the run inherited, and then the run&rsquo;s
            own changes. That pair is expected, not an off-by-one.
          </p>
        </>
      )}

      {selected && <RevisionFiles revision={selected} />}
    </section>
  );
}

function ParityBanner({ parity }) {
  if (!parity) return null;

  if (!parity.has_revision) {
    // Not "in sync" (that would be a lie) and not an error (it is a normal
    // state for a target nobody has snapshotted yet).
    return (
      <div className="banner">
        No revisions yet, so there is nothing to compare against the files on disk.
      </div>
    );
  }

  if (parity.in_sync) {
    return (
      <div className="banner success">
        In sync — revision {parity.rev} matches the files on disk.
      </div>
    );
  }

  return (
    <div className="banner parity-bad">
      <strong>Not in sync</strong> — revision {parity.rev} disagrees with the files on disk.
      <ParityPaths label="Only in the database (missing on disk)" paths={parity.only_in_db} />
      <ParityPaths label="Only on disk (never snapshotted)" paths={parity.only_on_disk} />
      <ParityPaths label="Different contents" paths={parity.modified} />
    </div>
  );
}

function ParityPaths({ label, paths }) {
  if (!paths || paths.length === 0) return null;
  return (
    <div className="parity-group">
      <span className="parity-label">{label}</span>
      <ul className="parity-paths">
        {paths.map((p) => (
          <li key={p} className="mono">
            {p}
          </li>
        ))}
      </ul>
    </div>
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
      // rather than read off the shared disk.
      const text = await api.revisionFile(revision.id, path);
      setContents(typeof text === "string" ? text : JSON.stringify(text, null, 2));
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

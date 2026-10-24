import { useState } from "react";
import { api } from "../api.js";
import { Field, LiveRunBanner } from "../components.jsx";
import { ConfigFields, noteLines, useFields } from "../config-form.jsx";

// A target's configuration, as a form.
//
// It used to be a file in the harness's own git repo, which meant a thirty
// second change was an edit-and-redeploy. A changed base URL re-renders the
// generated playwright.config.ts, which is a tree diff, which is a revision --
// so a configuration change is as reviewable as a code change, and shows up in
// the delivery commit like one.
//
// `locators` and `agentNotes` reach the agent through its prompt rather than
// through a tracked file, so changing them updates the row and commits nothing.
// The form says which is which rather than leaving the operator to wonder why
// one edit produced a revision and another did not.

export default function TargetConfig({ target, onSaved }) {
  const [form, set] = useFields({
    name: target.name,
    base_url: target.base_url,
    target_repo: target.target_repo,
    target_branch: target.target_branch,
    locators: target.locators || "",
  });
  const [notes, setNotes] = useState((target.agent_notes || []).join("\n"));
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setConflict("");
    setNotice("");
    try {
      const out = await api.updateTargetConfig(target.id, {
        ...form,
        agent_notes: noteLines(notes),
      });
      setNotice(
        out.revision
          ? `Saved. The generated Playwright config changed, so this is revision ${out.revision.rev}.`
          : "Saved. Nothing in the tree changed, so no revision was committed — these values reach the agent through its prompt.",
      );
      onSaved?.();
    } catch (e) {
      if (e.status === 409) setConflict(String(e.message || e));
      else setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card target-config">
      <div className="page-head">
        <h2>Configuration</h2>
      </div>

      <LiveRunBanner detail={conflict} />
      {error && <div className="error">{error}</div>}
      {notice && <div className="banner success">{notice}</div>}

      <form className="form-grid" onSubmit={submit}>
        <Field label="Display name">
          <input value={form.name} onChange={set("name")} required />
        </Field>
        <ConfigFields form={form} set={set} notes={notes} setNotes={setNotes} hints rows={5} />
        <button className="btn primary" disabled={busy}>
          {busy ? "Saving…" : "Save configuration"}
        </button>
      </form>
    </section>
  );
}

import { useEffect, useState } from "react";
import { api } from "../api.js";
import { Spinner } from "../components.jsx";

/**
 * User administration for one tenant (P5-14 / #46, stories 2 and 27).
 *
 * Invite and remove, nothing else: there is no role-change path, because the
 * server has none either -- `accounts.add_user` assigns a role at creation and
 * an `Action` member for a change nothing can perform is exactly what
 * `app/domain/audit.py` argues against. Changing somebody's role today means
 * removing the account and inviting it again, which is honest about what the
 * backend does.
 *
 * Rendered only for an admin, and that is **presentation**. The server's admin
 * dependency is what enforces story 2, so this component still renders a
 * refusal rather than treating one as impossible -- a panel that assumed it
 * could never be refused would show an empty table for a member, which reads
 * as "this tenant has no users".
 *
 * Its own component, with its own state, for the reason `PromptHistory` is:
 * the accounts of a tenant are nobody else's state, and hoisting them into
 * `Settings` would put a second unrelated concern in a page that already has
 * two.
 */
export default function Users() {
  const [users, setUsers] = useState(null);
  const [error, setError] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("member");
  // The account just created, held only to show its password. It exists in
  // this response and nowhere else -- nothing stores it, so nothing can show
  // it again -- which is why it is state rather than a toast that times out.
  const [invited, setInvited] = useState(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState("");

  async function load() {
    try {
      setUsers(await api.listUsers());
      setError("");
    } catch (e) {
      setError(String(e.message || e));
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function invite(e) {
    e.preventDefault();
    setBusy(true);
    setActionError("");
    try {
      const created = await api.inviteUser(email.trim(), role);
      setInvited(created);
      setEmail("");
      await load();
    } catch (err) {
      setActionError(String(err.message || err));
    } finally {
      setBusy(false);
    }
  }

  async function remove(user) {
    setBusy(true);
    setActionError("");
    try {
      await api.removeUser(user.id);
      await load();
    } catch (err) {
      // Kept on screen rather than cleared on the next render: the last-admin
      // refusal carries the remedy, and it is the only place that remedy is
      // written down.
      setActionError(String(err.message || err));
    } finally {
      setBusy(false);
    }
  }

  if (error) return <div className="error">{error}</div>;
  if (!users) return <Spinner />;

  return (
    <div className="users-panel">
      <table className="users">
        <tbody>
          {users.map((u) => (
            <tr key={u.id}>
              <td className="mono">{u.email}</td>
              <td>
                <span className={`pill pill-${u.role}`}>{u.role}</span>
              </td>
              <td>
                <button
                  className="btn ghost"
                  disabled={busy}
                  aria-label={`Remove ${u.email}`}
                  onClick={() => remove(u)}
                >
                  Remove
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <form className="invite" onSubmit={invite}>
        <label>
          Email
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="someone@example.com"
          />
        </label>
        <label>
          Role
          <select value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="member">member</option>
            <option value="admin">admin</option>
          </select>
        </label>
        <button className="btn" type="submit" disabled={busy}>
          Invite
        </button>
      </form>

      {actionError && <div className="banner banner-bad">{actionError}</div>}

      {invited && (
        <div className="banner banner-good invited">
          <strong>{invited.email}</strong> can now sign in with this password:
          <code className="one-time-password">{invited.password}</code>
          <span>
            Copy it now — it will not be shown again, and nothing here can
            recover it. If it is lost, remove the account and invite again.
          </span>
          <button className="btn ghost" onClick={() => setInvited(null)}>
            Done
          </button>
        </div>
      )}
    </div>
  );
}

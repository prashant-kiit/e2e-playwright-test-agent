import { useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { api } from "./api.js";
import NewTarget from "./pages/NewTarget.jsx";
import Login from "./pages/Login.jsx";
import Projects from "./pages/Projects.jsx";
import RunDetail from "./pages/RunDetail.jsx";
import Runs from "./pages/Runs.jsx";
import Settings from "./pages/Settings.jsx";

export default function App() {
  const [authed, setAuthed] = useState(null); // null = checking

  useEffect(() => {
    api
      .me()
      .then(() => setAuthed(true))
      .catch(() => setAuthed(false));
  }, []);

  if (authed === null) return <div className="center muted">Loading…</div>;
  if (!authed) return <Login onLogin={() => setAuthed(true)} />;

  return (
    <div className="layout">
      <Sidebar onLogout={() => setAuthed(false)} />
      <main className="content">
        <Routes>
          <Route path="/" element={<Navigate to="/projects" replace />} />
          <Route path="/projects" element={<Projects />} />
          <Route path="/targets/new" element={<NewTarget />} />
          <Route path="/runs" element={<Runs />} />
          <Route path="/runs/:id" element={<RunDetail />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<div className="muted">Not found.</div>} />
        </Routes>
      </main>
    </div>
  );
}

function Sidebar({ onLogout }) {
  const navigate = useNavigate();
  async function logout() {
    await api.logout().catch(() => {});
    onLogout();
    navigate("/");
  }
  return (
    <aside className="sidebar">
      <div className="brand">QA&nbsp;Portal</div>
      <nav>
        <NavLink to="/projects">Projects &amp; Targets</NavLink>
        <NavLink to="/targets/new">New Target</NavLink>
        <NavLink to="/runs">Run History</NavLink>
        <NavLink to="/settings">Settings</NavLink>
      </nav>
      <button className="btn ghost logout" onClick={logout}>
        Log out
      </button>
    </aside>
  );
}

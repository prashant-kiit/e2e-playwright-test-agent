// Thin fetch wrapper. Same-origin in dev (via the Vite proxy), so the session
// cookie is sent automatically; `credentials: "include"` keeps prod safe too.

async function req(method, path, body) {
  const opts = { method, credentials: "include", headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  if (res.status === 401) throw new AuthError();
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch {}
    throw new ApiError(detail, res.status);
  }
  if (res.status === 204) return null;
  const ct = res.headers.get("content-type") || "";
  return ct.includes("application/json") ? res.json() : res.text();
}

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}
export class AuthError extends Error {}

export const api = {
  // auth
  me: () => req("GET", "/auth/me"),
  login: (password) => req("POST", "/auth/login", { password }),
  logout: () => req("POST", "/auth/logout"),

  // projects + targets
  listProjects: () => req("GET", "/projects"),
  createProject: (name) => req("POST", "/projects", { name }),
  listTargets: (projectId) =>
    req("GET", projectId ? `/targets?project_id=${projectId}` : "/targets"),
  createTarget: (projectId, app, name) =>
    req("POST", `/projects/${projectId}/targets`, { app, name }),

  // runs
  listRuns: (targetId) =>
    req("GET", targetId ? `/runs?target_id=${targetId}` : "/runs"),
  getRun: (id) => req("GET", `/runs/${id}`),
  startRun: (targetId, story_id, mode) =>
    req("POST", `/targets/${targetId}/runs`, { story_id, mode }),
  runSteps: (id) => req("GET", `/runs/${id}/steps`),
  runArtifacts: (id) => req("GET", `/runs/${id}/artifacts`),
  pauseRun: (id) => req("POST", `/runs/${id}/pause`),
  resumeRun: (id) => req("POST", `/runs/${id}/resume`),
  stopRun: (id) => req("POST", `/runs/${id}/stop`),

  artifactContentUrl: (id) => `/artifacts/${id}/content`,
};

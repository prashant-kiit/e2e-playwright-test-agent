// Thin fetch wrapper. Same-origin in dev (via the Vite proxy), so the session
// cookie is sent automatically; `credentials: "include"` keeps prod safe too.

// `anyContentType` opts out of the HTML guard below, for the one route that
// serves a tracked file's own bytes.
async function req(method, path, body, { anyContentType = false } = {}) {
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
  // The API paths deliberately collide with SPA client routes, so a caching or
  // proxy slip can answer a data call with index.html. Handing that back as a
  // string turns into "e.map is not a function" three frames away and a blank
  // page; failing here says what actually happened.
  if (!anyContentType && ct.includes("text/html")) {
    throw new ApiError(
      `unexpected HTML from ${path} — expected data. The SPA shell was served ` +
        `for an API path; check the reverse proxy's Vary/Accept handling.`,
      res.status,
    );
  }
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

  // revisions (P2): the dual-written snapshot of a target's tracked tree.
  // Read-only except snapshotTarget, which is P2-only scaffolding -- in P3 the
  // filesystem is not authoritative and "snapshot the disk" stops meaning
  // anything.
  listRevisions: (targetId) => req("GET", `/targets/${targetId}/revisions`),
  snapshotTarget: (targetId) => req("POST", `/targets/${targetId}/revisions/snapshot`),
  targetParity: (targetId) => req("GET", `/targets/${targetId}/parity`),
  revisionFiles: (revisionId) => req("GET", `/revisions/${revisionId}/files`),
  // A tracked path contains slashes, so it travels as a query parameter and
  // needs no escaping scheme beyond the usual encoding.
  revisionFile: (revisionId, path) =>
    req("GET", `/revisions/${revisionId}/file?path=${encodeURIComponent(path)}`, undefined, {
      anyContentType: true,
    }),

  // repo introspection + bootstrap + settings
  listApps: () => req("GET", "/apps"),
  listStories: (app) => req("GET", `/apps/${app}/stories`),
  bootstrapApp: (body) => req("POST", "/apps/bootstrap", body),
  getPrompts: () => req("GET", "/prompts"),
  getSettings: () => req("GET", "/settings"),
};

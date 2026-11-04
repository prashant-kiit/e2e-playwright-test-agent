// Thin fetch wrapper. Same-origin in dev (via the Vite proxy), so the session
// cookies are sent automatically; `credentials: "include"` keeps prod safe too.
//
// The access cookie lives fifteen minutes now (the refresh cookie, thirty
// days), so a 401 mid-session is the *expected* case rather than a dead
// session: anyone who leaves a tab open over lunch comes back to one. This
// wrapper absorbs it -- 401, POST /auth/refresh, replay the original request --
// so no caller has to know the session is renewable, and an operator never sees
// a login form they did not need. A 401 that survives the refresh is a real
// one and surfaces as AuthError.

// Endpoints that must never trigger the dance. /auth/refresh would recurse;
// /auth/login and /auth/logout 401 for reasons a refresh cannot fix -- a wrong
// password is not an expired session, and refreshing one would replay the bad
// credentials against a freshly minted cookie.
const NO_REFRESH = new Set(["/auth/refresh", "/auth/login", "/auth/logout"]);

// In flight refresh, shared by every request that 401s while it runs. Without
// this, a page that loads three panels at once sends three refreshes.
let refreshing = null;

function refreshSession() {
  if (!refreshing) {
    refreshing = fetch("/auth/refresh", { method: "POST", credentials: "include" })
      .then((res) => res.ok)
      .catch(() => false)
      .finally(() => {
        refreshing = null;
      });
  }
  return refreshing;
}

async function req(method, path, body, { allowRefresh = true } = {}) {
  const opts = { method, credentials: "include", headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  if (res.status === 401) {
    // `allowRefresh: false` on the replay is what bounds this to one retry: a
    // second 401 is a session that cannot be saved, not a reason to loop.
    if (allowRefresh && !NO_REFRESH.has(path) && (await refreshSession())) {
      return req(method, path, body, { allowRefresh: false });
    }
    throw new AuthError();
  }
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
  if (ct.includes("text/html")) {
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

// A prompt's name carries a slash ("steps/2-plan.md") and the routes take it
// as a path parameter, so the slash must survive: each segment is encoded
// rather than the whole name. One function because three callers had the same
// `split/map/join` inline and a fourth would have copied it too.
function promptPath(name) {
  return `/prompts/${name.split("/").map(encodeURIComponent).join("/")}`;
}

export const api = {
  // auth
  me: () => req("GET", "/auth/me"),
  // Renew the access cookie, reporting success rather than throwing. For the
  // one caller that cannot go through `req` and so gets no automatic retry:
  // EventSource, which opens its own connection and, per spec, does *not*
  // reconnect after an HTTP error status -- so an expired access cookie would
  // otherwise close the live log for good.
  renewSession: () => refreshSession(),
  // The tenant slug goes with the email: an address is unique only within a
  // tenant now, so it no longer names an account on its own.
  login: (tenant, email, password) =>
    req("POST", "/auth/login", { tenant, email, password }),
  logout: () => req("POST", "/auth/logout"),

  // projects + targets. A target carries its own configuration now: creating
  // one writes the row and commits its revision 1 from the templates.
  listProjects: () => req("GET", "/projects"),
  createProject: (name) => req("POST", "/projects", { name }),
  listTargets: (projectId) =>
    req("GET", projectId ? `/targets?project_id=${projectId}` : "/targets"),
  createTarget: (projectId, body) => req("POST", `/projects/${projectId}/targets`, body),
  updateTargetConfig: (targetId, body) => req("PATCH", `/targets/${targetId}/config`, body),

  // stories: the portal is the only way one gets in, and every write commits
  // one operator-authored revision.
  listStories: (targetId) => req("GET", `/targets/${targetId}/stories`),
  readStory: (targetId, storyId) => req("GET", `/targets/${targetId}/stories/${storyId}`),
  writeStory: (targetId, storyId, body) =>
    req("PUT", `/targets/${targetId}/stories/${storyId}`, body),
  deleteStory: (targetId, storyId) =>
    req("DELETE", `/targets/${targetId}/stories/${storyId}`),

  // The target's own GitHub credential (P5-03). The token goes up and never
  // comes back: no response here carries it or its ciphertext, so there is
  // nothing for this layer to hold on to.
  targetCredential: (targetId) => req("GET", `/targets/${targetId}/credential`),
  saveTargetPat: (targetId, token) => req("PUT", `/targets/${targetId}/pat`, { token }),
  clearTargetPat: (targetId) => req("DELETE", `/targets/${targetId}/pat`),

  // delivery: "delivered" or "N revisions ahead", from one Postgres query.
  deliveryState: (targetId) => req("GET", `/targets/${targetId}/delivery`),

  // This tenant's usage against its plan caps (P5-04). One call, because the
  // panel needs both halves: a count with no denominator cannot be rendered as
  // "2 of 3". No tenant id in the path -- there is no tenant to ask about but
  // your own.
  usage: () => req("GET", "/usage"),

  // The write half (P5-13). Tenant-admin only, enforced server-side; the
  // portal hides the control for a member but the 403 is what decides.
  //
  // `caps` carries **only the caps being changed**: the route distinguishes an
  // omitted key (leave it alone) from an explicit `null` (unmetered), so this
  // must not helpfully fill in the ones the admin did not touch. Returns the
  // same shape as `usage()`, recomputed, so the panel renders what was stored.
  setUsageCaps: (caps) => req("PUT", "/usage/caps", caps),

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

  // revisions: the operator's window into a target's tree. Read-only -- the
  // writers are ingest (at a run's step boundaries) and the story/config
  // writes above. There is no snapshot action: the filesystem is not
  // authoritative, so "snapshot the disk" stopped meaning anything. There is no
  // parity either: with one copy of the truth there is nothing to compare it to.
  listRevisions: (targetId) => req("GET", `/targets/${targetId}/revisions`),
  revisionFiles: (revisionId) => req("GET", `/revisions/${revisionId}/files`),
  // A tracked path contains slashes, so it travels as a query parameter and
  // needs no escaping scheme beyond the usual encoding.
  // Always text: the route serves every tracked path as text/plain so the
  // bytes reach the viewer exactly as they were stored.
  revisionFile: (revisionId, path) =>
    req("GET", `/revisions/${revisionId}/file?path=${encodeURIComponent(path)}`),

  // prompts + settings
  getPrompts: () => req("GET", "/prompts"),
  savePrompt: (name, content) =>
    req("PUT", promptPath(name), { content }),
  // Every revision of one prompt, oldest first (#39). Fetched when a customer
  // opens the history rather than with the prompt list: a body is the largest
  // column in this schema and a page of prompts would otherwise pull every
  // superseded version of all of them on load.
  getPromptHistory: (name) => req("GET", `${promptPath(name)}/history`),
  getSettings: () => req("GET", "/settings"),
};

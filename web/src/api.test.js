import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, AuthError, api } from "./api.js";

function mockFetch(status, body, contentType = "application/json") {
  global.fetch = vi.fn().mockResolvedValue({
    status,
    ok: status >= 200 && status < 300,
    statusText: "err",
    headers: { get: () => contentType },
    json: async () => body,
    text: async () => (typeof body === "string" ? body : JSON.stringify(body)),
  });
}

describe("api wrapper", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("returns parsed json on 2xx", async () => {
    mockFetch(200, [{ id: 1, name: "p" }]);
    expect(await api.listProjects()).toEqual([{ id: 1, name: "p" }]);
  });

  it("sends credentials and a JSON body on POST", async () => {
    mockFetch(201, { id: 9 });
    await api.createProject("demo");
    const [path, opts] = global.fetch.mock.calls[0];
    expect(path).toBe("/projects");
    expect(opts.method).toBe("POST");
    expect(opts.credentials).toBe("include");
    expect(JSON.parse(opts.body)).toEqual({ name: "demo" });
  });

  it("throws AuthError on 401", async () => {
    mockFetch(401, {});
    await expect(api.me()).rejects.toBeInstanceOf(AuthError);
  });

  it("throws ApiError carrying detail + status on 409", async () => {
    mockFetch(409, { detail: "app already has a live run" });
    await expect(api.startRun(1, "SCRUM-201", "full")).rejects.toMatchObject({
      status: 409,
      message: "app already has a live run",
    });
  });

  it("builds the artifact content url", () => {
    expect(api.artifactContentUrl(7)).toBe("/artifacts/7/content");
  });

  it("refuses an HTML document where data was expected", async () => {
    // The API paths collide with SPA routes, so a caching slip can hand the
    // app its own index.html. Returning it as a string blanks the page with a
    // cryptic "e.map is not a function"; this says what actually happened.
    mockFetch(200, "<!doctype html><title>QA Portal</title>", "text/html");
    await expect(api.listProjects()).rejects.toThrow(/unexpected html/i);
  });

  it("returns a tracked json file verbatim, not re-encoded", async () => {
    // The route serves every tracked path as text/plain precisely so this
    // cannot become JSON.parse -> JSON.stringify, which is not the stored bytes.
    const raw = '{"name":   "qa",\n  "private": true}\n';
    mockFetch(200, raw, "text/plain; charset=utf-8");
    expect(await api.revisionFile(3, "package.json")).toBe(raw);
  });

  it("encodes a tracked path into the revision file query", async () => {
    mockFetch(200, "// cart\n", "text/plain");
    await api.revisionFile(3, "tests/checkout/cart.spec.ts");
    const [path] = global.fetch.mock.calls[0];
    expect(path).toBe("/revisions/3/file?path=tests%2Fcheckout%2Fcart.spec.ts");
  });

  it("returns a tracked file as text, not json", async () => {
    mockFetch(200, "export default {};\n", "text/plain");
    expect(await api.revisionFile(3, "playwright.config.ts")).toBe("export default {};\n");
  });
});

// --- the authoring surface (P3) -----------------------------------------
//
// With the mount gone the portal is the only way a story gets in, so these
// paths and verbs are part of the contract rather than an implementation
// detail of one page.

describe("the authoring surface", () => {
  beforeEach(() => mockFetch(200, {}));

  it("creates a target under its project", async () => {
    await api.createTarget(3, { app: "demo", name: "Demo" });
    const [path, opts] = global.fetch.mock.calls[0];
    expect(path).toBe("/projects/3/targets");
    expect(opts.method).toBe("POST");
  });

  it("edits a target's configuration with PATCH, so one field can be sent", async () => {
    await api.updateTargetConfig(3, { base_url: "https://x.example.com" });
    const [path, opts] = global.fetch.mock.calls[0];
    expect(path).toBe("/targets/3/config");
    expect(opts.method).toBe("PATCH");
  });

  it("writes a story by its id, so a save is idempotent", async () => {
    await api.writeStory(3, "SCRUM-1", { story_id: "SCRUM-1", slug: "a", content: "#" });
    const [path, opts] = global.fetch.mock.calls[0];
    expect(path).toBe("/targets/3/stories/SCRUM-1");
    expect(opts.method).toBe("PUT");
  });

  it("deletes a story by its id", async () => {
    await api.deleteStory(3, "SCRUM-1");
    const [path, opts] = global.fetch.mock.calls[0];
    expect(path).toBe("/targets/3/stories/SCRUM-1");
    expect(opts.method).toBe("DELETE");
  });

  it("reads a target's stories from its own route, not from an app list", async () => {
    await api.listStories(3);
    expect(global.fetch.mock.calls[0][0]).toBe("/targets/3/stories");
  });

  it("asks the database whether a target is delivered", async () => {
    await api.deliveryState(3);
    const [path, opts] = global.fetch.mock.calls[0];
    expect(path).toBe("/targets/3/delivery");
    expect(opts.method).toBe("GET");
  });

  it("offers no way to snapshot a filesystem or to read parity", () => {
    // Both described a second copy of the truth that no longer exists.
    expect(api.snapshotTarget).toBeUndefined();
    expect(api.targetParity).toBeUndefined();
    expect(api.listApps).toBeUndefined();
    expect(api.bootstrapApp).toBeUndefined();
  });
});

describe("the expired-access-token dance", () => {
  beforeEach(() => vi.restoreAllMocks());

  function mockSequence(responses) {
    const calls = [];
    global.fetch = vi.fn().mockImplementation((path, opts) => {
      calls.push([path, opts]);
      const r = responses.shift();
      return Promise.resolve({
        status: r.status,
        ok: r.status >= 200 && r.status < 300,
        statusText: "err",
        headers: { get: () => "application/json" },
        json: async () => r.body ?? {},
        text: async () => JSON.stringify(r.body ?? {}),
      });
    });
    return calls;
  }

  it("refreshes once on 401 and replays the original request", async () => {
    // The access cookie has expired mid-session: the call 401s, /auth/refresh
    // mints a new one, and the retry succeeds -- so the operator never sees it.
    const calls = mockSequence([
      { status: 401 },
      { status: 200, body: { ok: true } },
      { status: 200, body: [{ id: 1, name: "p" }] },
    ]);
    expect(await api.listProjects()).toEqual([{ id: 1, name: "p" }]);
    expect(calls.map(([p]) => p)).toEqual(["/projects", "/auth/refresh", "/projects"]);
    expect(calls[1][1].method).toBe("POST");
  });

  it("gives up with AuthError when the refresh also fails", async () => {
    // The refresh token has aged out too: there is nothing left to trade, so
    // this has to surface as AuthError and send the operator to the login form.
    const calls = mockSequence([{ status: 401 }, { status: 401 }]);
    await expect(api.listProjects()).rejects.toBeInstanceOf(AuthError);
    expect(calls.map(([p]) => p)).toEqual(["/projects", "/auth/refresh"]);
  });

  it("retries only once, so a 401 cannot loop", async () => {
    const calls = mockSequence([
      { status: 401 },
      { status: 200, body: { ok: true } },
      { status: 401 },
    ]);
    await expect(api.listProjects()).rejects.toBeInstanceOf(AuthError);
    expect(calls).toHaveLength(3);
  });

  it("does not try to refresh a failed login", async () => {
    // A wrong password is not an expired session; refreshing here would be a
    // wasted round trip, and on a live session it would replay the bad
    // credentials against a freshly minted cookie.
    const calls = mockSequence([{ status: 401 }]);
    await expect(api.login("default", "dev@example.com", "wrong")).rejects.toBeInstanceOf(
      AuthError,
    );
    expect(calls.map(([p]) => p)).toEqual(["/auth/login"]);
  });

  it("shares one refresh between concurrent 401s", async () => {
    // Three panels load at once and all three 401. One /auth/refresh, not
    // three -- each extra one would be minting a cookie that invalidates
    // nothing but costs a round trip.
    const calls = mockSequence([
      { status: 401 },
      { status: 401 },
      { status: 401 },
      { status: 200, body: { ok: true } },
      { status: 200, body: [] },
      { status: 200, body: [] },
      { status: 200, body: [] },
    ]);
    await Promise.all([api.listProjects(), api.listProjects(), api.listProjects()]);
    expect(calls.filter(([p]) => p === "/auth/refresh")).toHaveLength(1);
  });
});

describe("renewSession", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("reports whether the session was renewed, and never throws", async () => {
    // For callers outside the fetch wrapper -- EventSource, which bypasses
    // `req` entirely and cannot be retried by it.
    global.fetch = vi.fn().mockResolvedValue({ ok: true, status: 200 });
    expect(await api.renewSession()).toBe(true);

    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 401 });
    expect(await api.renewSession()).toBe(false);

    global.fetch = vi.fn().mockRejectedValue(new Error("offline"));
    expect(await api.renewSession()).toBe(false);
  });

  it("posts to /auth/refresh with credentials", async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: true, status: 200 });
    await api.renewSession();
    const [path, opts] = global.fetch.mock.calls[0];
    expect(path).toBe("/auth/refresh");
    expect(opts.method).toBe("POST");
    expect(opts.credentials).toBe("include");
  });
});

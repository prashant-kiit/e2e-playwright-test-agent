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

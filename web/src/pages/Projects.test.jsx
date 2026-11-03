import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { api } from "../api.js";
import Projects from "./Projects.jsx";

// The three panels of a target are the page's only interaction beyond starting
// a run: a tab that opens nothing is the failure this covers, and it is not one
// the panel components' own tests can see.

vi.mock("../api.js", () => ({
  api: {
    listProjects: vi.fn(),
    listTargets: vi.fn(),
    createProject: vi.fn(),
    listStories: vi.fn(),
    deliveryState: vi.fn(),
    targetCredential: vi.fn(),
    saveTargetPat: vi.fn(),
    clearTargetPat: vi.fn(),
    updateTargetConfig: vi.fn(),
    listRevisions: vi.fn(),
    revisionFiles: vi.fn(),
    usage: vi.fn(),
    startRun: vi.fn(),
  },
}));

const TARGET = {
  id: 1,
  project_id: 7,
  app: "saucedemo",
  name: "Sauce Demo",
  base_url: "https://www.saucedemo.com",
  target_repo: "owner/tests",
  target_branch: "master",
  locators: "data-test attributes",
  agent_notes: [],
};

function renderPage() {
  return render(
    <MemoryRouter>
      <Projects />
    </MemoryRouter>,
  );
}

describe("Projects", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.listProjects.mockResolvedValue([{ id: 7, name: "demo" }]);
    api.listTargets.mockResolvedValue([TARGET]);
    api.listStories.mockResolvedValue([]);
    api.deliveryState.mockResolvedValue({
      rev: 3,
      delivered: false,
      delivered_sha: null,
      revisions_ahead: 2,
      ever_delivered: true,
      summary: "2 revision(s) ahead of the last delivered one",
      credential_state: "valid",
      pat_expires_at: null,
      credential_warning: null,
    });
    api.targetCredential.mockResolvedValue({
      app: "saucedemo",
      state: "valid",
      expires_at: null,
      days_until_expiry: null,
      expiring_soon: false,
      warning: null,
      login: "acme-ci",
    });
    api.listRevisions.mockResolvedValue([]);
    // The quota panel (P5-04). Mocked here rather than left undefined
    // because `load()` calls it: an unmocked `api.usage` throws inside the
    // page's own loader and sends every test in this file down the error
    // path, where they would still pass while rendering none of the page.
    api.usage.mockResolvedValue({
      live_runs: 0,
      runs_this_month: 2,
      max_concurrent_runs: 3,
      monthly_run_quota: 10,
      at_concurrency_cap: false,
      at_monthly_quota: false,
    });
  });

  it("shows the target with its delivery state", async () => {
    renderPage();

    expect(await screen.findByText("Sauce Demo")).toBeInTheDocument();
    expect(await screen.findByText(/2 revs ahead/i)).toBeInTheDocument();
  });

  it("opens each panel from its own button, and closes it again", async () => {
    renderPage();
    await screen.findByText("Sauce Demo");

    for (const [button, heading] of [
      [/^stories$/i, /user stories/i],
      [/^config$/i, /configuration/i],
      [/^revisions$/i, /revision/i],
      [/^credential$/i, /github credential/i],
    ]) {
      await userEvent.click(screen.getByRole("button", { name: button }));
      expect(await screen.findByRole("heading", { name: heading })).toBeInTheDocument();
      await userEvent.click(screen.getByRole("button", { name: /^hide/i }));
      await waitFor(() =>
        expect(screen.queryByRole("heading", { name: heading })).not.toBeInTheDocument(),
      );
    }
  });

  // The credential badge rides on the delivery state the row already fetches
  // (P5-03), so "this target cannot deliver" is visible without opening a
  // panel -- which is the whole value of warning before an expiry lapses.

  it("warns on the target row when no credential is stored", async () => {
    api.deliveryState.mockResolvedValue({
      rev: 3,
      delivered: false,
      delivered_sha: null,
      revisions_ahead: 2,
      ever_delivered: true,
      summary: "2 revision(s) ahead of the last delivered one",
      credential_state: "absent",
      pat_expires_at: null,
      credential_warning:
        "No GitHub credential is stored for this target, so delivery cannot run.",
    });

    renderPage();

    expect(await screen.findByText(/no github token/i)).toBeInTheDocument();
  });

  it("warns on the target row when the credential was rejected", async () => {
    api.deliveryState.mockResolvedValue({
      rev: 3,
      delivered: true,
      delivered_sha: "a".repeat(40),
      revisions_ahead: 0,
      ever_delivered: true,
      summary: "delivered (revision 3)",
      credential_state: "invalid",
      pat_expires_at: null,
      credential_warning: "GitHub rejected this credential the last time we delivered.",
    });

    renderPage();

    expect(await screen.findByText(/token rejected/i)).toBeInTheDocument();
  });

  it("warns on the target row when the credential is about to expire", async () => {
    api.deliveryState.mockResolvedValue({
      rev: 3,
      delivered: true,
      delivered_sha: "a".repeat(40),
      revisions_ahead: 0,
      ever_delivered: true,
      summary: "delivered (revision 3)",
      credential_state: "valid",
      pat_expires_at: "2026-11-10T00:00:00Z",
      credential_warning: "This GitHub credential expires in 7 days.",
    });

    renderPage();

    expect(await screen.findByText(/token expires soon/i)).toBeInTheDocument();
  });

  it("shows no credential badge when the credential is healthy", async () => {
    renderPage();
    await screen.findByText("Sauce Demo");

    expect(screen.queryByText(/no github token/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/token rejected/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/token expires soon/i)).not.toBeInTheDocument();
  });

  // --- the quota panel and a refused start (P5-04) ------------------------
  //
  // This surface shipped untested. The two defects a review then found by
  // reading it were a cap rendered as "2 of undefined" (pinned in
  // UsageMeter.test.jsx) and an unguarded async reload after a refusal, which
  // is pinned below.

  // A refusal as the page sees one: `req()` turns a non-ok response into an
  // error carrying `detail` as its message and the HTTP status. Built here as
  // a plain object rather than the real `ApiError`, because this file mocks
  // the whole api module and the page reads only these two fields.
  function refusal(status, detail) {
    return Object.assign(new Error(detail), { status });
  }

  const QUOTA_DETAIL =
    "this tenant already has 3 of 3 runs going at once; wait for one to " +
    "finish or stop one, then start this again";

  async function pressStart() {
    api.listStories.mockResolvedValue([{ story_id: "SCRUM-201", title: "Checkout" }]);
    renderPage();
    await screen.findByText("Sauce Demo");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /start qa run/i })).toBeEnabled(),
    );
    await userEvent.click(screen.getByRole("button", { name: /start qa run/i }));
  }

  it("shows the tenant's usage against its caps", async () => {
    renderPage();

    expect(await screen.findByText("0 of 3")).toBeInTheDocument();
    expect(await screen.findByText("2 of 10")).toBeInTheDocument();
  });

  it("still renders the projects when the usage read fails", async () => {
    // The gauges are information; the targets are what the operator came for.
    api.usage.mockRejectedValue(new Error("usage unavailable"));

    renderPage();

    expect(await screen.findByText("Sauce Demo")).toBeInTheDocument();
    expect(screen.queryByText(/of 3$/)).not.toBeInTheDocument();
  });

  it("shows a quota refusal in the server's own words", async () => {
    // Not reworded in the browser: the message names the cap, the usage and a
    // remedy that differs per cap, so rewriting it here would mean two places
    // deciding what "out of quota" means.
    api.startRun.mockRejectedValue(refusal(429, QUOTA_DETAIL));

    await pressStart();

    expect(await screen.findByText(QUOTA_DETAIL)).toBeInTheDocument();
  });

  it("re-reads the usage after a refusal so the gauges agree with it", async () => {
    api.startRun.mockRejectedValue(refusal(429, QUOTA_DETAIL));
    api.usage
      .mockResolvedValueOnce({
        live_runs: 0,
        runs_this_month: 2,
        max_concurrent_runs: 3,
        monthly_run_quota: 10,
        at_concurrency_cap: false,
        at_monthly_quota: false,
      })
      .mockResolvedValue({
        live_runs: 3,
        runs_this_month: 5,
        max_concurrent_runs: 3,
        monthly_run_quota: 10,
        at_concurrency_cap: true,
        at_monthly_quota: false,
      });

    await pressStart();

    expect(await screen.findByText("3 of 3")).toBeInTheDocument();
    expect(await screen.findByText(/at your concurrent-run cap/)).toBeInTheDocument();
  });

  it("reports a failed reload instead of leaving a rejected promise", async () => {
    // The guarded `reload()`. `load` is async and the post-429 call does not
    // await it, so an unguarded call made a failing re-read an unhandled
    // rejection -- invisible until it took a page down.
    api.startRun.mockRejectedValue(refusal(429, QUOTA_DETAIL));
    api.listProjects
      .mockResolvedValueOnce([{ id: 7, name: "demo" }])
      .mockRejectedValue(new Error("the reload itself failed"));

    await pressStart();

    expect(await screen.findByText("the reload itself failed")).toBeInTheDocument();
  });

  it("keeps the queue explanation for a busy app, which is a different refusal", async () => {
    // 409 and 429 must not collapse into one message: "this app is busy" and
    // "your tenant is out of allowance" have different remedies.
    api.startRun.mockRejectedValue(refusal(409, "app already has a live run 4"));

    await pressStart();

    expect(await screen.findByText(/runs are not queued/i)).toBeInTheDocument();
  });
});

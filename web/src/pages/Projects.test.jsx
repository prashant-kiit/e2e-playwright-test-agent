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
    updateTargetConfig: vi.fn(),
    listRevisions: vi.fn(),
    revisionFiles: vi.fn(),
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
    });
    api.listRevisions.mockResolvedValue([]);
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
    ]) {
      await userEvent.click(screen.getByRole("button", { name: button }));
      expect(await screen.findByRole("heading", { name: heading })).toBeInTheDocument();
      await userEvent.click(screen.getByRole("button", { name: /^hide/i }));
      await waitFor(() =>
        expect(screen.queryByRole("heading", { name: heading })).not.toBeInTheDocument(),
      );
    }
  });
});

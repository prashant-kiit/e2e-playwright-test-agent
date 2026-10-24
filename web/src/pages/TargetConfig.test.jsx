import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api.js";
import TargetConfig from "./TargetConfig.jsx";

vi.mock("../api.js", () => ({ api: { updateTargetConfig: vi.fn() } }));

const TARGET = {
  id: 1,
  app: "saucedemo",
  name: "Sauce Demo",
  base_url: "https://www.saucedemo.com",
  target_repo: "owner/tests",
  target_branch: "master",
  locators: "data-test attributes",
  agent_notes: ["the seed logs in", "firefox is flaky"],
};

describe("TargetConfig", () => {
  beforeEach(() => vi.clearAllMocks());

  it("loads the target's current configuration into the form", () => {
    render(<TargetConfig target={TARGET} />);

    expect(screen.getByDisplayValue("https://www.saucedemo.com")).toBeInTheDocument();
    expect(screen.getByDisplayValue("owner/tests")).toBeInTheDocument();
    // Agent notes are a list on the row and one-per-line in the form. Read the
    // value off the node: getByDisplayValue collapses the newline.
    expect(screen.getByLabelText(/agent notes/i).value).toBe(
      "the seed logs in\nfirefox is flaky",
    );
  });

  it("sends the notes back as a list, not as a blob of text", async () => {
    api.updateTargetConfig.mockResolvedValue({ revision: null, stories: [] });
    render(<TargetConfig target={TARGET} />);

    await userEvent.click(screen.getByRole("button", { name: /save configuration/i }));

    await waitFor(() => expect(api.updateTargetConfig).toHaveBeenCalled());
    const [, body] = api.updateTargetConfig.mock.calls[0];
    expect(body.agent_notes).toEqual(["the seed logs in", "firefox is flaky"]);
  });

  it("reports the revision a base-URL change committed", async () => {
    api.updateTargetConfig.mockResolvedValue({
      revision: { id: 20, rev: 2, parent_rev: 1, tree_hash: "a".repeat(64), produced_by_run_id: null, author: "operator", created_at: "2026-10-24T10:00:00Z", file_count: 11 },
      stories: [],
    });
    render(<TargetConfig target={TARGET} />);

    await userEvent.clear(screen.getByDisplayValue("https://www.saucedemo.com"));
    await userEvent.type(
      screen.getByLabelText(/base url/i),
      "https://moved.example.com",
    );
    await userEvent.click(screen.getByRole("button", { name: /save configuration/i }));

    // A config change is a tree diff, which is a revision -- as reviewable as a
    // code change, and the form says so rather than saving silently.
    expect(await screen.findByText(/revision 2/i)).toBeInTheDocument();
  });

  it("says when an edit reaches the agent's prompt rather than the tree", async () => {
    api.updateTargetConfig.mockResolvedValue({ revision: null, stories: [] });
    render(<TargetConfig target={TARGET} />);

    await userEvent.click(screen.getByRole("button", { name: /save configuration/i }));

    expect(await screen.findByText(/no revision was committed/i)).toBeInTheDocument();
    expect(screen.getByText(/through its prompt/i)).toBeInTheDocument();
  });

  it("explains a live-run conflict rather than queueing the edit", async () => {
    const e = new Error("target 1 has a live run (7) … pause or stop it, then save again.");
    e.status = 409;
    api.updateTargetConfig.mockRejectedValue(e);
    render(<TargetConfig target={TARGET} />);

    await userEvent.click(screen.getByRole("button", { name: /save configuration/i }));

    expect(await screen.findByText(/this target has a live run/i)).toBeInTheDocument();
  });

  it("reports a refused configuration as the operator's typo", async () => {
    const e = new Error("base URL must be an absolute http(s) URL, got 'nope'");
    e.status = 422;
    api.updateTargetConfig.mockRejectedValue(e);
    render(<TargetConfig target={TARGET} />);

    await userEvent.click(screen.getByRole("button", { name: /save configuration/i }));

    expect(await screen.findByText(/absolute http\(s\) URL/i)).toBeInTheDocument();
  });
});

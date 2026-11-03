import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api.js";
import Settings from "./Settings.jsx";

vi.mock("../api.js", () => ({
  api: {
    getSettings: vi.fn(),
    getPrompts: vi.fn(),
    savePrompt: vi.fn(),
  },
}));

const SETTINGS = {
  runner: "claude",
  fake_delay: 0,
  runs_dir: "/var/qa/runs",
  worktrees_dir: "/var/qa/worktrees",
  model: "default",
  anthropic_api_key_set: true,
};

const PROMPTS = [
  { name: "qa_system_prompt.md", content: "The overview.\n", rev: 1 },
  { name: "steps/2-plan.md", content: "Plan it.\n", rev: 1 },
  { name: "steps/3-explore.md", content: "Explore it.\n", rev: 4 },
];

describe("Settings: the Prompts panel (P5-06)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getSettings.mockResolvedValue(SETTINGS);
    api.getPrompts.mockResolvedValue(PROMPTS);
  });

  it("marks a prompt still on the shipped default apart from one the tenant has tuned", async () => {
    render(<Settings />);

    const plan = (await screen.findByText("steps/2-plan.md")).closest("button");
    const explore = screen.getByText("steps/3-explore.md").closest("button");

    // rev 1 is the seeded default; rev 4 is three overrides deep, and a
    // customer needs to see at a glance which prompts they have tuned.
    expect(plan).toHaveTextContent("default");
    expect(explore).toHaveTextContent("edited · rev 4");
  });

  it("saves an edit as the next revision and shows what came back", async () => {
    api.savePrompt.mockResolvedValue({
      name: "steps/2-plan.md",
      content: "Plan it my way.\n",
      rev: 2,
    });

    render(<Settings />);
    await userEvent.click(await screen.findByText("steps/2-plan.md"));

    const box = screen.getByRole("textbox");
    await userEvent.clear(box);
    await userEvent.type(box, "Plan it my way.");
    await userEvent.click(screen.getByRole("button", { name: /save as revision 2/i }));

    await waitFor(() =>
      expect(api.savePrompt).toHaveBeenCalledWith("steps/2-plan.md", "Plan it my way."),
    );
    // The row is replaced in place, so the new revision shows without a reload.
    expect(await screen.findByText(/edited · rev 2/)).toBeInTheDocument();
  });

  it("cannot save until something is actually changed", async () => {
    render(<Settings />);
    await userEvent.click(await screen.findByText("steps/2-plan.md"));

    expect(screen.getByRole("button", { name: /save as revision 2/i })).toBeDisabled();

    await userEvent.type(screen.getByRole("textbox"), "more");
    expect(screen.getByRole("button", { name: /save as revision 2/i })).toBeEnabled();
  });

  it("keeps the draft and reports a refused save rather than losing the edit", async () => {
    api.savePrompt.mockRejectedValue(new Error("no such prompt: steps/2-plan.md"));

    render(<Settings />);
    await userEvent.click(await screen.findByText("steps/2-plan.md"));
    await userEvent.type(screen.getByRole("textbox"), "my change");
    await userEvent.click(screen.getByRole("button", { name: /save as revision 2/i }));

    expect(await screen.findByText(/no such prompt/i)).toBeInTheDocument();
    // The edit is still there to retry with.
    expect(screen.getByRole("textbox")).toHaveValue("Plan it.\nmy change");
  });

  it("discards changes back to the saved body", async () => {
    render(<Settings />);
    await userEvent.click(await screen.findByText("steps/2-plan.md"));

    await userEvent.type(screen.getByRole("textbox"), "scratch that");
    await userEvent.click(screen.getByRole("button", { name: /discard changes/i }));

    expect(screen.getByRole("textbox")).toHaveValue("Plan it.\n");
  });
});

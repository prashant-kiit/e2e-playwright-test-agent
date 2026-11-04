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
    getPromptHistory: vi.fn(),
    // The page asks who is logged in, to decide whether to render the
    // user-administration panel (P5-14). These tests are about prompts, so it
    // answers "member" and the panel stays away; `Users.test.jsx` owns it.
    me: vi.fn(),
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
    api.me.mockResolvedValue({ email: "dev@example.com", role: "member" });
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


// --- the revision history (#39) ------------------------------------------
//
// P5-06 showed "edited · rev 4" and gave a customer no way to see what any of
// those four revisions said or when they were saved. #30's story 24 asks for
// the versioning "so that I can see what changed and when", and for a prompt
// that steers an unattended agent against their own application, "which of my
// edits made this run behave differently?" is the question it exists for.

const HISTORY = [
  {
    name: "steps/3-explore.md",
    content: "Explore it.\n",
    rev: 1,
    created_at: "2026-10-01T09:00:00Z",
  },
  {
    name: "steps/3-explore.md",
    content: "Explore it slowly.\n",
    rev: 2,
    created_at: "2026-10-02T09:00:00Z",
  },
  {
    name: "steps/3-explore.md",
    content: "Explore it slowly.\nAnd check the cart.\n",
    rev: 3,
    created_at: "2026-10-03T09:00:00Z",
  },
];

describe("Settings: a prompt's revision history (#39)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getSettings.mockResolvedValue(SETTINGS);
    api.getPrompts.mockResolvedValue(PROMPTS);
    api.me.mockResolvedValue({ email: "dev@example.com", role: "member" });
    api.getPromptHistory.mockResolvedValue(HISTORY);
  });

  it("does not fetch any history until a customer asks for one", async () => {
    // Three prompts on the page and one request each on load would be three
    // requests for bodies nobody has asked to see -- and every prompt body is
    // the largest column in this schema.
    render(<Settings />);
    await screen.findByText("steps/3-explore.md");

    expect(api.getPromptHistory).not.toHaveBeenCalled();
  });

  it("lists the revisions newest first, each with when it was saved", async () => {
    render(<Settings />);
    await userEvent.click(await screen.findByText("steps/3-explore.md"));
    await userEvent.click(screen.getByRole("button", { name: /history/i }));

    await waitFor(() =>
      expect(api.getPromptHistory).toHaveBeenCalledWith("steps/3-explore.md"),
    );

    const revisions = await screen.findAllByTestId("prompt-revision");
    // Newest first: "what did I just change" is the common question, and the
    // backend answers oldest-first because that is the order the rows are in.
    expect(revisions.map((r) => r.textContent)).toEqual([
      expect.stringContaining("rev 3"),
      expect.stringContaining("rev 2"),
      expect.stringContaining("rev 1"),
    ]);
    expect(revisions[0]).toHaveTextContent("2026");
  });

  it("shows a revision's diff against the one before it", async () => {
    render(<Settings />);
    await userEvent.click(await screen.findByText("steps/3-explore.md"));
    await userEvent.click(screen.getByRole("button", { name: /history/i }));
    const revisions = await screen.findAllByTestId("prompt-revision");

    await userEvent.click(revisions[0].querySelector("button"));

    // rev 3 added one line to rev 2 and changed nothing else, and that is
    // what a diff has to show -- a customer comparing two bodies by eye is
    // doing the work this panel exists to do for them.
    const diff = await screen.findByTestId("prompt-diff");
    expect(diff).toHaveTextContent("+ And check the cart.");
    expect(diff).not.toHaveTextContent("+ Explore it slowly.");
  });

  it("marks the first revision as the shipped default rather than diffing it", async () => {
    render(<Settings />);
    await userEvent.click(await screen.findByText("steps/3-explore.md"));
    await userEvent.click(screen.getByRole("button", { name: /history/i }));
    const revisions = await screen.findAllByTestId("prompt-revision");

    await userEvent.click(revisions[2].querySelector("button"));

    // There is nothing before revision 1, so the only honest thing to show is
    // the body itself.
    expect(await screen.findByTestId("prompt-revision-body")).toHaveTextContent(
      "Explore it.",
    );
    expect(screen.queryByTestId("prompt-diff")).not.toBeInTheDocument();
  });

  it("says so when a prompt has only ever been the default", async () => {
    api.getPromptHistory.mockResolvedValue([
      {
        name: "steps/2-plan.md",
        content: "Plan it.\n",
        rev: 1,
        created_at: null,
      },
    ]);

    render(<Settings />);
    await userEvent.click(await screen.findByText("steps/2-plan.md"));
    await userEvent.click(screen.getByRole("button", { name: /history/i }));

    expect(await screen.findByText(/never been edited/i)).toBeInTheDocument();
    // `created_at` is null for a default that is not yet a row, and rendering
    // that as a date would be an invented fact in the one panel whose job is
    // to say when things changed.
    expect(screen.queryByText(/invalid date/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/NaN/)).not.toBeInTheDocument();
  });

  it("reports a failed history fetch instead of an empty panel", async () => {
    // P5-04's lesson: a surface that degrades to nothing is a surface that
    // ships broken and passes its tests.
    api.getPromptHistory.mockRejectedValue(new Error("history unavailable"));

    render(<Settings />);
    await userEvent.click(await screen.findByText("steps/3-explore.md"));
    await userEvent.click(screen.getByRole("button", { name: /history/i }));

    expect(await screen.findByText(/history unavailable/i)).toBeInTheDocument();
  });
});

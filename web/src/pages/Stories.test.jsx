import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api.js";
import Stories from "./Stories.jsx";

vi.mock("../api.js", () => ({
  api: {
    listStories: vi.fn(),
    readStory: vi.fn(),
    writeStory: vi.fn(),
    deleteStory: vi.fn(),
  },
}));

const TARGET = { id: 1, app: "saucedemo", name: "Sauce Demo" };

const STORY = {
  story_id: "SCRUM-101",
  slug: "checkout",
  title: "E-commerce Checkout Process",
  file: "SCRUM-101-checkout.md",
  path: "user-stories/SCRUM-101-checkout.md",
};

const REV = (rev) => ({
  id: rev * 10,
  rev,
  parent_rev: rev - 1,
  tree_hash: "a".repeat(64),
  produced_by_run_id: null,
  author: "operator",
  created_at: "2026-10-24T10:00:00Z",
  file_count: 11,
});

function conflictError() {
  const e = new Error(
    "target 1 has a live run (7), which is working from an older revision. " +
      "Saving now would be reverted by that run's next snapshot, and there is no merge. " +
      "Wait for it to finish, or pause or stop it, then save again.",
  );
  e.status = 409;
  return e;
}

describe("Stories", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.listStories.mockResolvedValue([STORY]);
  });

  it("lists the target's stories from the head revision", async () => {
    render(<Stories target={TARGET} />);

    expect(await screen.findByText("SCRUM-101")).toBeInTheDocument();
    expect(screen.getByText("E-commerce Checkout Process")).toBeInTheDocument();
    expect(api.listStories).toHaveBeenCalledWith(TARGET.id);
  });

  it("says a target with no stories cannot start a run yet", async () => {
    api.listStories.mockResolvedValue([]);
    render(<Stories target={TARGET} />);

    expect(await screen.findByText(/No stories yet/i)).toBeInTheDocument();
  });

  it("writes a new story and reports the revision it committed", async () => {
    api.listStories.mockResolvedValue([]);
    api.writeStory.mockResolvedValue({ revision: REV(2), stories: [STORY] });
    render(<Stories target={TARGET} />);
    await screen.findByText(/No stories yet/i);

    await userEvent.click(screen.getByRole("button", { name: /new story/i }));
    await userEvent.type(screen.getByPlaceholderText("SCRUM-201"), "SCRUM-101");
    await userEvent.type(screen.getByPlaceholderText("auth"), "checkout");
    await userEvent.type(screen.getByRole("textbox", { name: /story \(markdown\)/i }), "# story");
    await userEvent.click(screen.getByRole("button", { name: /save as a revision/i }));

    await waitFor(() => expect(api.writeStory).toHaveBeenCalled());
    const [targetId, storyId, body] = api.writeStory.mock.calls[0];
    expect(targetId).toBe(TARGET.id);
    expect(storyId).toBe("SCRUM-101");
    expect(body.slug).toBe("checkout");
    expect(await screen.findByText(/Saved as revision 2/i)).toBeInTheDocument();
  });

  it("loads a story's stored content to edit it", async () => {
    api.readStory.mockResolvedValue({ ...STORY, content: "# User Story: SCRUM-101 - Checkout" });
    render(<Stories target={TARGET} />);
    await screen.findByText("SCRUM-101");

    await userEvent.click(screen.getByRole("button", { name: /edit/i }));

    await waitFor(() => expect(api.readStory).toHaveBeenCalledWith(TARGET.id, "SCRUM-101"));
    expect(await screen.findByDisplayValue(/# User Story: SCRUM-101 - Checkout/)).toBeInTheDocument();
  });

  it("says so when a save changed nothing, instead of claiming a revision", async () => {
    api.readStory.mockResolvedValue({ ...STORY, content: "# same" });
    api.writeStory.mockResolvedValue({ revision: null, stories: [STORY] });
    render(<Stories target={TARGET} />);
    await screen.findByText("SCRUM-101");
    await userEvent.click(screen.getByRole("button", { name: /edit/i }));
    await screen.findByDisplayValue("# same");

    await userEvent.click(screen.getByRole("button", { name: /save as a revision/i }));

    expect(await screen.findByText(/No change/i)).toBeInTheDocument();
  });

  it("deletes a story and says its plan and suite were left alone", async () => {
    api.deleteStory.mockResolvedValue({ revision: REV(3), stories: [] });
    render(<Stories target={TARGET} />);
    await screen.findByText("SCRUM-101");

    await userEvent.click(screen.getByRole("button", { name: /delete/i }));

    await waitFor(() => expect(api.deleteStory).toHaveBeenCalledWith(TARGET.id, "SCRUM-101"));
    const notice = await screen.findByText(/Deleted SCRUM-101 as revision 3/i);
    expect(notice).toHaveTextContent(/left in place/i);
  });

  it("explains a live-run conflict rather than queueing the edit", async () => {
    api.readStory.mockResolvedValue({ ...STORY, content: "# story" });
    api.writeStory.mockRejectedValue(conflictError());
    render(<Stories target={TARGET} />);
    await screen.findByText("SCRUM-101");
    await userEvent.click(screen.getByRole("button", { name: /edit/i }));
    await screen.findByDisplayValue("# story");

    await userEvent.click(screen.getByRole("button", { name: /save as a revision/i }));

    // There is no merge logic anywhere in this system, so the portal must say
    // why the edit was refused and what to do -- not pretend to queue it.
    const banner = await screen.findByText(/this target has a live run/i);
    expect(banner).toBeInTheDocument();
    expect(screen.getByText(/pause or stop it/i)).toBeInTheDocument();
    expect(screen.queryByText(/queued/i)).not.toBeInTheDocument();
  });

  it("keeps the editor open after a conflict so the edit is not lost", async () => {
    api.readStory.mockResolvedValue({ ...STORY, content: "# story" });
    api.writeStory.mockRejectedValue(conflictError());
    render(<Stories target={TARGET} />);
    await screen.findByText("SCRUM-101");
    await userEvent.click(screen.getByRole("button", { name: /edit/i }));
    await screen.findByDisplayValue("# story");

    await userEvent.click(screen.getByRole("button", { name: /save as a revision/i }));
    await screen.findByText(/this target has a live run/i);

    expect(screen.getByDisplayValue("# story")).toBeInTheDocument();
  });
});

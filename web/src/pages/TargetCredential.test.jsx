import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api.js";
import TargetCredential from "./TargetCredential.jsx";

vi.mock("../api.js", () => ({
  api: {
    targetCredential: vi.fn(),
    saveTargetPat: vi.fn(),
    clearTargetPat: vi.fn(),
  },
}));

const TARGET = { id: 7, app: "saucedemo", name: "Sauce Demo", target_repo: "owner/tests" };

const ABSENT = {
  app: "saucedemo",
  state: "absent",
  expires_at: null,
  days_until_expiry: null,
  expiring_soon: false,
  warning:
    "No GitHub credential is stored for this target, so delivery cannot run. Save a personal access token with repo + workflow scope.",
  login: null,
};

const VALID = {
  ...ABSENT,
  state: "valid",
  warning: null,
  login: "acme-ci",
};

describe("TargetCredential", () => {
  beforeEach(() => vi.clearAllMocks());

  it("says delivery cannot run when no token is stored", async () => {
    api.targetCredential.mockResolvedValue(ABSENT);

    render(<TargetCredential target={TARGET} />);

    expect(await screen.findByText(/delivery cannot run/i)).toBeInTheDocument();
  });

  it("saves the pasted token and reports the account it authors as", async () => {
    api.targetCredential.mockResolvedValue(ABSENT);
    api.saveTargetPat.mockResolvedValue(VALID);
    render(<TargetCredential target={TARGET} />);
    await screen.findByText(/delivery cannot run/i);

    await userEvent.type(screen.getByLabelText(/personal access token/i), "ghp_abc123");
    await userEvent.click(screen.getByRole("button", { name: /save token/i }));

    await waitFor(() => expect(api.saveTargetPat).toHaveBeenCalledWith(7, "ghp_abc123"));
    expect(await screen.findByText(/acme-ci/)).toBeInTheDocument();
  });

  it("never leaves the pasted token in the form after a save", async () => {
    api.targetCredential.mockResolvedValue(ABSENT);
    api.saveTargetPat.mockResolvedValue(VALID);
    render(<TargetCredential target={TARGET} />);
    await screen.findByText(/delivery cannot run/i);

    const input = screen.getByLabelText(/personal access token/i);
    await userEvent.type(input, "ghp_abc123");
    await userEvent.click(screen.getByRole("button", { name: /save token/i }));

    await waitFor(() => expect(input.value).toBe(""));
  });

  it("masks the token as it is typed", async () => {
    api.targetCredential.mockResolvedValue(ABSENT);
    render(<TargetCredential target={TARGET} />);
    await screen.findByText(/delivery cannot run/i);

    expect(screen.getByLabelText(/personal access token/i)).toHaveAttribute(
      "type",
      "password",
    );
  });

  it("shows the refusal reason when a token is missing a scope", async () => {
    api.targetCredential.mockResolvedValue(ABSENT);
    api.saveTargetPat.mockRejectedValue({
      status: 422,
      message: "this token is missing the workflow scope(s)",
    });
    render(<TargetCredential target={TARGET} />);
    await screen.findByText(/delivery cannot run/i);

    await userEvent.type(screen.getByLabelText(/personal access token/i), "ghp_abc123");
    await userEvent.click(screen.getByRole("button", { name: /save token/i }));

    expect(await screen.findByText(/missing the workflow scope/i)).toBeInTheDocument();
  });

  it("warns before an expiry lapses, with the number of days", async () => {
    api.targetCredential.mockResolvedValue({
      ...VALID,
      expires_at: "2026-11-17T00:00:00Z",
      days_until_expiry: 14,
      expiring_soon: true,
      warning:
        "This GitHub credential expires in 14 days. Save a new token before then to keep delivery working.",
    });

    render(<TargetCredential target={TARGET} />);

    expect(await screen.findByText(/expires in 14 days/i)).toBeInTheDocument();
  });

  it("says GitHub rejected the credential, and that runs are unaffected", async () => {
    api.targetCredential.mockResolvedValue({
      ...VALID,
      state: "invalid",
      warning:
        "GitHub rejected this credential the last time we delivered. Save a new personal access token; runs are unaffected.",
    });

    render(<TargetCredential target={TARGET} />);

    expect(await screen.findByText(/runs are unaffected/i)).toBeInTheDocument();
  });

  it("clears a stored credential", async () => {
    api.targetCredential.mockResolvedValue(VALID);
    api.clearTargetPat.mockResolvedValue(ABSENT);
    render(<TargetCredential target={TARGET} />);
    await screen.findByRole("button", { name: /remove token/i });

    await userEvent.click(screen.getByRole("button", { name: /remove token/i }));

    await waitFor(() => expect(api.clearTargetPat).toHaveBeenCalledWith(7));
    expect(await screen.findByText(/delivery cannot run/i)).toBeInTheDocument();
  });

  it("offers nothing to remove when there is no credential", async () => {
    api.targetCredential.mockResolvedValue(ABSENT);

    render(<TargetCredential target={TARGET} />);
    await screen.findByText(/delivery cannot run/i);

    expect(screen.queryByRole("button", { name: /remove token/i })).not.toBeInTheDocument();
  });
});

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api.js";
import Bootstrap from "./Bootstrap.jsx";

vi.mock("../api.js", () => ({ api: { bootstrapApp: vi.fn() } }));

describe("Bootstrap", () => {
  beforeEach(() => vi.clearAllMocks());

  it("submits the form and shows the result", async () => {
    api.bootstrapApp.mockResolvedValue({ app: "my-app", bootstrap: { ok: true, output: "done" } });
    render(<Bootstrap />);
    await userEvent.type(screen.getByPlaceholderText("my-app"), "my-app");
    await userEvent.type(screen.getByPlaceholderText("My App"), "My App");
    await userEvent.click(screen.getByRole("button", { name: /create target/i }));

    await waitFor(() => expect(api.bootstrapApp).toHaveBeenCalled());
    const body = api.bootstrapApp.mock.calls[0][0];
    expect(body.app).toBe("my-app");
    expect(body.do_bootstrap).toBe(true);
    expect(await screen.findByText(/Created/)).toBeInTheDocument();
    expect(await screen.findByText(/bootstrapped/i)).toBeInTheDocument();
    expect(screen.getByText("done")).toBeInTheDocument();
  });

  it("reports a failed target-repo sync as an outcome, not an error", async () => {
    api.bootstrapApp.mockResolvedValue({
      app: "my-app",
      bootstrap: { ok: false, output: "no GitHub token" },
    });
    render(<Bootstrap />);
    await userEvent.type(screen.getByPlaceholderText("my-app"), "my-app");
    await userEvent.type(screen.getByPlaceholderText("My App"), "My App");
    await userEvent.click(screen.getByRole("button", { name: /create target/i }));

    // The app folder was still created, so the banner reports the outcome and
    // the reason rather than discarding both.
    expect(await screen.findByText(/Created/)).toBeInTheDocument();
    expect(await screen.findByText(/bootstrap failed/i)).toBeInTheDocument();
    expect(screen.getByText("no GitHub token")).toBeInTheDocument();
  });

  it("keeps the submit button disabled until app + name are filled", () => {
    render(<Bootstrap />);
    expect(screen.getByRole("button", { name: /create target/i })).toBeDisabled();
  });
});

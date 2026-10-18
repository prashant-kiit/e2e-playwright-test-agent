import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api.js";
import Login from "./Login.jsx";

vi.mock("../api.js", () => ({ api: { login: vi.fn() } }));

describe("Login", () => {
  beforeEach(() => vi.clearAllMocks());

  it("submits the password and calls onLogin on success", async () => {
    api.login.mockResolvedValue({ ok: true });
    const onLogin = vi.fn();
    render(<Login onLogin={onLogin} />);
    await userEvent.type(screen.getByPlaceholderText("Password"), "s3cret");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(api.login).toHaveBeenCalledWith("s3cret");
    await waitFor(() => expect(onLogin).toHaveBeenCalled());
  });

  it("shows an error and does not call onLogin on failure", async () => {
    api.login.mockRejectedValue(new Error("401"));
    const onLogin = vi.fn();
    render(<Login onLogin={onLogin} />);
    await userEvent.type(screen.getByPlaceholderText("Password"), "wrong");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByText(/wrong password/i)).toBeInTheDocument();
    expect(onLogin).not.toHaveBeenCalled();
  });

  it("disables the button until a password is entered", () => {
    render(<Login onLogin={() => {}} />);
    expect(screen.getByRole("button", { name: /sign in/i })).toBeDisabled();
  });
});

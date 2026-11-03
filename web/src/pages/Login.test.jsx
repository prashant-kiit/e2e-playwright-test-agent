import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api.js";
import Login from "./Login.jsx";

vi.mock("../api.js", () => ({ api: { login: vi.fn() } }));

describe("Login", () => {
  beforeEach(() => vi.clearAllMocks());

  async function fill({ tenant = "default", email = "dev@example.com", password = "s3cret" } = {}) {
    const slug = screen.getByPlaceholderText("Tenant");
    await userEvent.clear(slug);
    if (tenant) await userEvent.type(slug, tenant);
    if (email) await userEvent.type(screen.getByPlaceholderText("Email"), email);
    if (password) await userEvent.type(screen.getByPlaceholderText("Password"), password);
  }

  it("submits the tenant, email and password and calls onLogin on success", async () => {
    api.login.mockResolvedValue({ ok: true });
    const onLogin = vi.fn();
    render(<Login onLogin={onLogin} />);
    await fill();
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(api.login).toHaveBeenCalledWith("default", "dev@example.com", "s3cret");
    await waitFor(() => expect(onLogin).toHaveBeenCalled());
  });

  it("defaults the tenant to `default`, the slug the migration seeds", async () => {
    // The single-tenant operator should not have to learn a new field to log in
    // the way they always have.
    render(<Login onLogin={() => {}} />);
    expect(screen.getByPlaceholderText("Tenant")).toHaveValue("default");
  });

  it("shows an error and does not call onLogin on failure", async () => {
    api.login.mockRejectedValue(new Error("401"));
    const onLogin = vi.fn();
    render(<Login onLogin={onLogin} />);
    await fill({ password: "wrong" });
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByText(/wrong tenant, email or password/i)).toBeInTheDocument();
    expect(onLogin).not.toHaveBeenCalled();
  });

  it("disables the button until all three fields are entered", async () => {
    render(<Login onLogin={() => {}} />);
    const button = () => screen.getByRole("button", { name: /sign in/i });
    await userEvent.clear(screen.getByPlaceholderText("Tenant"));
    expect(button()).toBeDisabled();
    await userEvent.type(screen.getByPlaceholderText("Email"), "dev@example.com");
    expect(button()).toBeDisabled();
    await userEvent.type(screen.getByPlaceholderText("Password"), "s3cret");
    expect(button()).toBeDisabled();
    await userEvent.type(screen.getByPlaceholderText("Tenant"), "default");
    expect(button()).toBeEnabled();
  });
});

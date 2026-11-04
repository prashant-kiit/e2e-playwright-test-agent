import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Users from "./Users.jsx";
import { api } from "../api.js";

// The user-administration panel (P5-14 / #46, stories 2 and 27).
//
// The panel is only rendered for an admin, and that is presentation: the
// server's admin dependency is what enforces story 2, and a member who reached
// the routes anyway is refused there. So the tests that matter here are about
// the two things a browser is uniquely responsible for: showing the one-time
// password (nothing can get it back) and not pretending a refused call worked.

vi.mock("../api.js", () => ({
  api: {
    listUsers: vi.fn(),
    inviteUser: vi.fn(),
    removeUser: vi.fn(),
  },
}));

const ADMIN = { id: 1, email: "admin@example.com", role: "admin" };
const MEMBER = { id: 2, email: "dev@example.com", role: "member" };

beforeEach(() => {
  vi.clearAllMocks();
  api.listUsers.mockResolvedValue([ADMIN, MEMBER]);
});

describe("Users panel", () => {
  it("lists this tenant's accounts with their roles", async () => {
    render(<Users />);

    expect(await screen.findByText("admin@example.com")).toBeInTheDocument();
    expect(screen.getByText("dev@example.com")).toBeInTheDocument();
    // Scoped to the table: the invite form's <select> has options with the
    // same two words, and a loose text match counts those too.
    const rows = screen.getAllByRole("row");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("admin");
    expect(rows[1]).toHaveTextContent("member");
  });

  it("shows the one-time password after an invite, and says it will not be shown again", async () => {
    // The whole reason this panel exists rather than a bare API: there is no
    // mail in this deployment, so the password is in the create response and
    // nowhere else. A panel that dropped it would create accounts nobody can
    // get into.
    api.inviteUser.mockResolvedValue({
      id: 3,
      email: "new@example.com",
      role: "member",
      password: "s3cret-one-time",
    });
    render(<Users />);
    await screen.findByText("admin@example.com");

    await userEvent.type(screen.getByLabelText(/email/i), "new@example.com");
    await userEvent.click(screen.getByRole("button", { name: /invite/i }));

    expect(await screen.findByText("s3cret-one-time")).toBeInTheDocument();
    expect(screen.getByText(/not be shown again/i)).toBeInTheDocument();
    expect(api.inviteUser).toHaveBeenCalledWith("new@example.com", "member");
  });

  it("can invite an admin as well as a member", async () => {
    api.inviteUser.mockResolvedValue({
      id: 3,
      email: "boss@example.com",
      role: "admin",
      password: "pw",
    });
    render(<Users />);
    await screen.findByText("admin@example.com");

    await userEvent.type(screen.getByLabelText(/email/i), "boss@example.com");
    await userEvent.selectOptions(screen.getByLabelText(/role/i), "admin");
    await userEvent.click(screen.getByRole("button", { name: /invite/i }));

    expect(api.inviteUser).toHaveBeenCalledWith("boss@example.com", "admin");
  });

  it("shows the server's reason when an invite is refused", async () => {
    api.inviteUser.mockRejectedValue(
      new Error("new@example.com already has an account in this tenant"),
    );
    render(<Users />);
    await screen.findByText("admin@example.com");

    await userEvent.type(screen.getByLabelText(/email/i), "new@example.com");
    await userEvent.click(screen.getByRole("button", { name: /invite/i }));

    expect(await screen.findByText(/already has an account/i)).toBeInTheDocument();
  });

  it("removes a user and drops them from the list", async () => {
    api.removeUser.mockResolvedValue(undefined);
    api.listUsers.mockResolvedValueOnce([ADMIN, MEMBER]).mockResolvedValueOnce([ADMIN]);
    render(<Users />);
    await screen.findByText("dev@example.com");

    await userEvent.click(
      screen.getByRole("button", { name: /remove dev@example.com/i }),
    );

    expect(api.removeUser).toHaveBeenCalledWith(2);
    await waitFor(() =>
      expect(screen.queryByText("dev@example.com")).not.toBeInTheDocument(),
    );
  });

  it("explains the last-admin refusal rather than failing silently", async () => {
    // The one refusal an operator has to read and act on: "make another admin
    // first" is the remedy, and it only exists in the server's message.
    api.removeUser.mockRejectedValue(
      new Error(
        "admin@example.com is the last admin of this tenant and cannot be removed; " +
          "make another admin first, then remove this one",
      ),
    );
    render(<Users />);
    await screen.findByText("admin@example.com");

    await userEvent.click(
      screen.getByRole("button", { name: /remove admin@example.com/i }),
    );

    expect(await screen.findByText(/last admin/i)).toBeInTheDocument();
    expect(screen.getByText(/make another admin first/i)).toBeInTheDocument();
    expect(screen.getByText("admin@example.com")).toBeInTheDocument();
  });

  it("renders nothing but a reason when the listing is refused", async () => {
    // A member who somehow reached this panel: the server refuses the read,
    // and the panel says so instead of showing an empty table that reads as
    // "this tenant has no users".
    api.listUsers.mockRejectedValue(new Error("tenant-admin role required"));
    render(<Users />);

    expect(await screen.findByText(/tenant-admin role required/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /invite/i })).not.toBeInTheDocument();
  });
});

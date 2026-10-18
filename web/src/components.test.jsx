import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatusPill } from "./components.jsx";

describe("StatusPill", () => {
  it("shows the status text and a status-specific class", () => {
    const { container } = render(<StatusPill status="running" />);
    expect(screen.getByText("running")).toBeInTheDocument();
    expect(container.querySelector(".pill-running")).toBeTruthy();
  });

  it("varies the class by status", () => {
    const { container } = render(<StatusPill status="failed" />);
    expect(container.querySelector(".pill-failed")).toBeTruthy();
  });
});

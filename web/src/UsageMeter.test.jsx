import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { UsageMeter } from "./components.jsx";

// The quota panel (P5-04). It shipped untested, and the two defects a review
// then found by *reading* it are both pinned here: the `null`-versus-absent cap
// and the pair of gauges that must be able to be full independently.

const METERED = {
  live_runs: 2,
  runs_this_month: 40,
  max_concurrent_runs: 3,
  monthly_run_quota: 500,
  at_concurrency_cap: false,
  at_monthly_quota: false,
};

describe("UsageMeter", () => {
  it("shows each cap as used-of-limit", () => {
    render(<UsageMeter usage={METERED} />);

    expect(screen.getByText("2 of 3")).toBeInTheDocument();
    expect(screen.getByText("40 of 500")).toBeInTheDocument();
  });

  it("renders nothing at all before the usage has loaded", () => {
    // The page renders its projects whether or not this read succeeded, so a
    // null here is the normal first paint and not an error state.
    const { container } = render(<UsageMeter usage={null} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("shows a count with no denominator for an unmetered cap", () => {
    // `null` is no cap, not a cap of zero: "7" and "no cap", never "7 of 0".
    render(
      <UsageMeter
        usage={{ ...METERED, live_runs: 7, max_concurrent_runs: null }}
      />,
    );

    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.getByText("no cap")).toBeInTheDocument();
    expect(screen.queryByText(/7 of/)).not.toBeInTheDocument();
  });

  it("treats a cap the server did not send as no cap rather than printing undefined", () => {
    // The defect behind `== null` instead of `=== null`. A field that went
    // missing used to render "2 of undefined", which is worse than useless:
    // it looks like a real denominator.
    const { max_concurrent_runs, ...withoutTheCap } = METERED;
    render(<UsageMeter usage={withoutTheCap} />);

    expect(screen.queryByText(/undefined/)).not.toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  it("marks a full gauge and says what to do about it", () => {
    render(
      <UsageMeter
        usage={{ ...METERED, live_runs: 3, at_concurrency_cap: true }}
      />,
    );

    expect(screen.getByText(/at your concurrent-run cap/)).toBeInTheDocument();
    // The remedy for this cap is to wait or stop a run -- it is self-clearing.
    expect(screen.getByText(/wait for a run to finish, or stop one/)).toBeInTheDocument();
  });

  it("gives the monthly cap its own remedy, because waiting cannot clear it", () => {
    render(
      <UsageMeter
        usage={{ ...METERED, runs_this_month: 500, at_monthly_quota: true }}
      />,
    );

    expect(screen.getByText(/out of runs for this calendar month/)).toBeInTheDocument();
    expect(screen.getByText(/resets on the 1st/)).toBeInTheDocument();
    expect(screen.queryByText(/wait for a run to finish/)).not.toBeInTheDocument();
  });

  it("can show both gauges full at once", () => {
    // The reason the server sends two independent flags rather than deriving
    // them from the one breach it would refuse with: both can be true, and a
    // gauge that read empty because the *other* was full would be wrong.
    const { container } = render(
      <UsageMeter
        usage={{
          ...METERED,
          live_runs: 3,
          runs_this_month: 500,
          at_concurrency_cap: true,
          at_monthly_quota: true,
        }}
      />,
    );

    expect(container.querySelectorAll(".usage-gauge-full")).toHaveLength(2);
  });

  it("marks only the gauge that is actually full", () => {
    const { container } = render(
      <UsageMeter
        usage={{ ...METERED, runs_this_month: 500, at_monthly_quota: true }}
      />,
    );

    expect(container.querySelectorAll(".usage-gauge-full")).toHaveLength(1);
    expect(screen.getByText("2 of 3")).toBeInTheDocument();
  });
});

// --- the write half (P5-13 / #45) ---------------------------------------
//
// Story 5: "only authorized users can ... change quotas". The control is shown
// only to an admin, and that is **presentation**: the server's `AdminDep` is
// what enforces it, and a member who reached the route anyway gets a 403. A
// hidden button is a tidier portal, not a permission.

describe("UsageMeter editing", () => {
  it("offers no way to change the caps to a non-admin", () => {
    render(<UsageMeter usage={METERED} canEdit={false} />);

    expect(screen.queryByRole("button", { name: /change caps/i })).not.toBeInTheDocument();
  });

  it("offers the caps to an admin, prefilled with what is stored", async () => {
    render(<UsageMeter usage={METERED} canEdit />);

    await userEvent.click(screen.getByRole("button", { name: /change caps/i }));

    expect(screen.getByLabelText(/concurrent runs/i)).toHaveValue(3);
    expect(screen.getByLabelText(/runs per month/i)).toHaveValue(500);
  });

  it("sends only the caps that were edited", async () => {
    // The distinction the route takes `model_fields_set` for: an untouched
    // field must not be sent, or raising one cap rewrites the other with a
    // value the admin never chose.
    const onSave = vi.fn().mockResolvedValue(METERED);
    render(<UsageMeter usage={METERED} canEdit onSave={onSave} />);
    await userEvent.click(screen.getByRole("button", { name: /change caps/i }));

    const field = screen.getByLabelText(/concurrent runs/i);
    await userEvent.clear(field);
    await userEvent.type(field, "9");
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));

    expect(onSave).toHaveBeenCalledWith({ max_concurrent_runs: 9 });
  });

  it("sends an explicit null when a cap is emptied, which means unmetered", async () => {
    // Emptying the box is how "no cap" is expressed, and it has to reach the
    // server as `null` rather than as an omission or as 0 -- those are three
    // different requests and only one of them means unmetered.
    const onSave = vi.fn().mockResolvedValue(METERED);
    render(<UsageMeter usage={METERED} canEdit onSave={onSave} />);
    await userEvent.click(screen.getByRole("button", { name: /change caps/i }));

    await userEvent.clear(screen.getByLabelText(/runs per month/i));
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));

    expect(onSave).toHaveBeenCalledWith({ monthly_run_quota: null });
  });

  it("shows the server's refusal rather than pretending the change landed", async () => {
    const onSave = vi.fn().mockRejectedValue(new Error("tenant-admin role required"));
    render(<UsageMeter usage={METERED} canEdit onSave={onSave} />);
    await userEvent.click(screen.getByRole("button", { name: /change caps/i }));

    const field = screen.getByLabelText(/concurrent runs/i);
    await userEvent.clear(field);
    await userEvent.type(field, "9");
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));

    expect(await screen.findByText(/tenant-admin role required/i)).toBeInTheDocument();
    // Still open, so the typed values are not lost to a failed save.
    expect(screen.getByLabelText(/concurrent runs/i)).toHaveValue(9);
  });

  it("renders the caps the server returned after a save, not the typed ones", async () => {
    // The server is the authority on what was stored: it clamps nothing today,
    // but a panel that showed the request rather than the response would be
    // lying the first time it does.
    const onSave = vi.fn().mockResolvedValue({ ...METERED, max_concurrent_runs: 4 });
    render(<UsageMeter usage={METERED} canEdit onSave={onSave} />);
    await userEvent.click(screen.getByRole("button", { name: /change caps/i }));

    const field = screen.getByLabelText(/concurrent runs/i);
    await userEvent.clear(field);
    await userEvent.type(field, "9");
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));

    expect(await screen.findByText("2 of 4")).toBeInTheDocument();
  });
});

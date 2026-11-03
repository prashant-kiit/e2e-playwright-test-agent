/**
 * The live log stream and the 15-minute access cookie.
 *
 * `EventSource` bypasses the fetch wrapper, so none of `api.js`'s
 * refresh-on-401 applies to it, and per spec it does **not** reconnect after an
 * HTTP error status -- it fires `error` once and stops. That combination is why
 * shortening the access cookie's life needed this: an operator who opens a run
 * page on a tab left idle past the expiry used to get a week-long cookie and a
 * working stream, and would otherwise now get a log pane that is silently and
 * permanently empty while the status beside it keeps polling.
 */
import { act, render, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api.js";
import RunDetail from "./RunDetail.jsx";

vi.mock("../api.js", () => ({
  api: {
    getRun: vi.fn(),
    runSteps: vi.fn(),
    runArtifacts: vi.fn(),
    renewSession: vi.fn(),
    artifactContentUrl: (id) => `/artifacts/${id}/content`,
  },
}));

/** Every instance built during a test, so the reopen is observable. */
let opened = [];

class FakeEventSource {
  constructor(url) {
    this.url = url;
    this.closed = false;
    this.listeners = {};
    opened.push(this);
  }
  addEventListener(name, fn) {
    this.listeners[name] = fn;
  }
  close() {
    this.closed = true;
  }
  /** What the browser does when the connection answers 401. */
  async fail() {
    await act(async () => {
      await this.onerror?.(new Event("error"));
    });
  }
  async emit(data) {
    await act(async () => {
      this.onmessage?.({ data: JSON.stringify(data) });
    });
  }
}

function renderRun() {
  return render(
    <MemoryRouter initialEntries={["/runs/7"]}>
      <Routes>
        <Route path="/runs/:id" element={<RunDetail />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("RunDetail live log stream", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    opened = [];
    global.EventSource = FakeEventSource;
    // A finished run, so the 2s status poll does not stay armed.
    api.getRun.mockResolvedValue({ id: 7, status: "passed", target_id: 1 });
    api.runSteps.mockResolvedValue([]);
    api.runArtifacts.mockResolvedValue([]);
  });

  it("renews the session and reopens the stream when the connection fails", async () => {
    api.renewSession.mockResolvedValue(true);
    renderRun();
    await waitFor(() => expect(opened).toHaveLength(1));

    await opened[0].fail();

    await waitFor(() => expect(opened).toHaveLength(2));
    expect(api.renewSession).toHaveBeenCalledTimes(1);
    expect(opened[0].closed).toBe(true);
    expect(opened[1].url).toBe("/runs/7/events");
  });

  it("gives up when the session cannot be renewed", async () => {
    // The refresh cookie has aged out too: reopening would 401 forever.
    api.renewSession.mockResolvedValue(false);
    renderRun();
    await waitFor(() => expect(opened).toHaveLength(1));

    await opened[0].fail();

    await waitFor(() => expect(api.renewSession).toHaveBeenCalledTimes(1));
    expect(opened).toHaveLength(1);
    expect(opened[0].closed).toBe(true);
  });

  it("does not reopen twice for one unrecovered failure", async () => {
    // Guards the loop: a stream that fails again immediately after a reopen is
    // failing for some reason a cookie cannot fix.
    api.renewSession.mockResolvedValue(true);
    renderRun();
    await waitFor(() => expect(opened).toHaveLength(1));

    await opened[0].fail();
    await waitFor(() => expect(opened).toHaveLength(2));
    await opened[1].fail();

    await waitFor(() => expect(opened[1].closed).toBe(true));
    expect(opened).toHaveLength(2);
  });

  it("allows another reopen once the stream has delivered a line", async () => {
    // A long run can outlive more than one expiry; a stream that is working
    // again has earned a fresh retry budget.
    api.renewSession.mockResolvedValue(true);
    renderRun();
    await waitFor(() => expect(opened).toHaveLength(1));

    await opened[0].fail();
    await waitFor(() => expect(opened).toHaveLength(2));
    await opened[1].emit({ line: "still going" });
    await opened[1].fail();

    await waitFor(() => expect(opened).toHaveLength(3));
  });
});

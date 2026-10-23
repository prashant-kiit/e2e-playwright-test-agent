import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api.js";
import Revisions from "./Revisions.jsx";

vi.mock("../api.js", () => ({
  api: {
    listRevisions: vi.fn(),
    snapshotTarget: vi.fn(),
    targetParity: vi.fn(),
    revisionFiles: vi.fn(),
    revisionFile: vi.fn(),
  },
}));

const TARGET = { id: 1, app: "saucedemo", name: "Sauce Demo" };

const REV_2 = {
  id: 22,
  rev: 2,
  parent_rev: 1,
  tree_hash: "b".repeat(64),
  produced_by_run_id: 7,
  author: "run:20261023-saucedemo-abc123",
  created_at: "2026-10-23T12:00:00Z",
  file_count: 11,
};
const REV_1 = {
  id: 11,
  rev: 1,
  parent_rev: null,
  tree_hash: "a".repeat(64),
  produced_by_run_id: null,
  author: "baseline",
  created_at: "2026-10-23T11:00:00Z",
  file_count: 10,
};

const IN_SYNC = {
  has_revision: true,
  in_sync: true,
  rev: 2,
  tree_hash: "b".repeat(64),
  only_in_db: [],
  only_on_disk: [],
  modified: [],
};

function arrange({ revisions = [REV_2, REV_1], parity = IN_SYNC, files = [], contents = "" } = {}) {
  api.listRevisions.mockResolvedValue(revisions);
  api.targetParity.mockResolvedValue(parity);
  api.revisionFiles.mockResolvedValue(files);
  api.revisionFile.mockResolvedValue(contents);
}

describe("Revisions panel", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows the head revision number and its tree hash", async () => {
    arrange();
    const { container } = render(<Revisions target={TARGET} />);

    await screen.findByRole("button", { name: /^rev 2$/i });
    expect(container.querySelector(".rev-head")).toHaveTextContent("rev 2");
    // The tree hash is long, so the panel shows a short prefix under a title
    // carrying the whole thing.
    expect(container.querySelector(".rev-head code")).toHaveAttribute(
      "title",
      "b".repeat(64),
    );
    expect(container.querySelector(".rev-head code")).toHaveTextContent("bbbbbbbbbbbb");
  });

  it("lists every revision newest first, with author and file count", async () => {
    arrange();
    render(<Revisions target={TARGET} />);

    await screen.findByRole("button", { name: /^rev 2$/i });
    const rows = screen.getAllByRole("row").slice(1); // drop the header row
    expect(rows[0]).toHaveTextContent("2");
    expect(rows[1]).toHaveTextContent("baseline");
    expect(rows[0]).toHaveTextContent("11");
    expect(rows[1]).toHaveTextContent("10");
  });

  it("explains the baseline-plus-changes pair on a first run", async () => {
    arrange();
    render(<Revisions target={TARGET} />);

    // Two revisions for what feels like one piece of work reads like an
    // off-by-one unless the portal says otherwise.
    const hint = await screen.findByText(/first run leaves/i);
    expect(hint).toHaveTextContent(/two revisions/i);
    expect(hint).toHaveTextContent(/inherited/i);
    expect(hint).toHaveTextContent(/not an off-by-one/i);
  });

  it("renders a green banner when the head revision matches disk", async () => {
    arrange();
    const { container } = render(<Revisions target={TARGET} />);

    expect(await screen.findByText(/in sync/i)).toBeInTheDocument();
    expect(container.querySelector(".banner")).toHaveClass("success");
  });

  it("names the offending paths when parity is out of sync", async () => {
    arrange({
      parity: {
        has_revision: true,
        in_sync: false,
        rev: 2,
        tree_hash: "b".repeat(64),
        only_in_db: ["tests/checkout/gone.spec.ts"],
        only_on_disk: ["tests/checkout/new.spec.ts"],
        modified: ["tests/checkout/cart.spec.ts"],
      },
    });
    const { container } = render(<Revisions target={TARGET} />);

    expect(await screen.findByText(/not in sync/i)).toBeInTheDocument();
    expect(container.querySelector(".banner")).not.toHaveClass("success");
    // A mismatch must read as a bug report, so every path is named.
    expect(screen.getByText("tests/checkout/gone.spec.ts")).toBeInTheDocument();
    expect(screen.getByText("tests/checkout/new.spec.ts")).toBeInTheDocument();
    expect(screen.getByText("tests/checkout/cart.spec.ts")).toBeInTheDocument();
    expect(screen.getByText(/only in the database/i)).toBeInTheDocument();
    expect(screen.getByText(/only on disk/i)).toBeInTheDocument();
    expect(screen.getByText(/different contents/i)).toBeInTheDocument();
  });

  it("reports a never-snapshotted target as its own state, not as in sync", async () => {
    arrange({
      revisions: [],
      parity: {
        has_revision: false,
        in_sync: false,
        rev: null,
        tree_hash: null,
        only_in_db: [],
        only_on_disk: [],
        modified: [],
      },
    });
    const { container } = render(<Revisions target={TARGET} />);

    expect(await screen.findByText(/No revisions yet\. Take a snapshot/i)).toBeInTheDocument();
    expect(container.querySelector(".banner")).toHaveTextContent(/nothing to compare/i);
    expect(screen.queryByText(/in sync/i)).not.toBeInTheDocument();
    expect(container.querySelector(".banner")).not.toHaveClass("success");
  });

  it("takes a snapshot on demand and reloads", async () => {
    arrange({ revisions: [], parity: { has_revision: false, in_sync: false, rev: null, tree_hash: null, only_in_db: [], only_on_disk: [], modified: [] } });
    api.snapshotTarget.mockResolvedValue({ created: true, revision: REV_1 });
    render(<Revisions target={TARGET} />);

    await screen.findByText(/No revisions yet\. Take a snapshot/i);
    arrange({ revisions: [REV_1], parity: { ...IN_SYNC, rev: 1 } });
    await userEvent.click(screen.getByRole("button", { name: /snapshot now/i }));

    await waitFor(() => expect(api.snapshotTarget).toHaveBeenCalledWith(TARGET.id));
    expect(await screen.findByText(/Snapshotted: revision 1/i)).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /^rev 1$/i })).toBeInTheDocument();
  });

  it("says so when a snapshot finds nothing to commit", async () => {
    arrange();
    api.snapshotTarget.mockResolvedValue({ created: false, revision: REV_2 });
    render(<Revisions target={TARGET} />);

    await screen.findByRole("button", { name: /^rev 2$/i });
    await userEvent.click(screen.getByRole("button", { name: /snapshot now/i }));

    expect(await screen.findByText(/No change .* nothing was committed/i)).toBeInTheDocument();
  });

  it("lists the selected revision's files with their sizes", async () => {
    arrange({
      files: [
        { path: "package.json", blob_key: "tenant/1/blobs/aa", size: 15 },
        { path: "tests/checkout/cart.spec.ts", blob_key: "tenant/1/blobs/bb", size: 1024 },
      ],
    });
    render(<Revisions target={TARGET} />);

    await userEvent.click(await screen.findByRole("button", { name: /^rev 2$/i }));

    await waitFor(() => expect(api.revisionFiles).toHaveBeenCalledWith(REV_2.id));
    expect(await screen.findByText("tests/checkout/cart.spec.ts")).toBeInTheDocument();
    expect(screen.getByText("package.json")).toBeInTheDocument();
    expect(screen.getByText(/1.0 KB|1024/)).toBeInTheDocument();
  });

  it("shows one file's contents, fetched from blob storage", async () => {
    arrange({
      files: [{ path: "tests/checkout/cart.spec.ts", blob_key: "tenant/1/blobs/bb", size: 9 }],
      contents: "// cart\n",
    });
    render(<Revisions target={TARGET} />);

    await userEvent.click(await screen.findByRole("button", { name: /^rev 2$/i }));
    await userEvent.click(await screen.findByText("tests/checkout/cart.spec.ts"));

    await waitFor(() =>
      expect(api.revisionFile).toHaveBeenCalledWith(REV_2.id, "tests/checkout/cart.spec.ts"),
    );
    expect(await screen.findByText("// cart")).toBeInTheDocument();
  });

  it("reports a failure to read a file instead of showing an empty viewer", async () => {
    arrange({
      files: [{ path: "tests/checkout/cart.spec.ts", blob_key: "tenant/1/blobs/bb", size: 9 }],
    });
    api.revisionFile.mockRejectedValue(new Error("storage error: no such key"));
    render(<Revisions target={TARGET} />);

    await userEvent.click(await screen.findByRole("button", { name: /^rev 2$/i }));
    await userEvent.click(await screen.findByText("tests/checkout/cart.spec.ts"));

    expect(await screen.findByText(/storage error/i)).toBeInTheDocument();
  });
});

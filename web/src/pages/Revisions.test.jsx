import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api.js";
import Revisions from "./Revisions.jsx";

// The parity banner's tests and the snapshot action's tests are deleted, not
// adapted. Parity compared the database against an authoritative filesystem,
// and there is no longer a second copy of the truth for it to compare against;
// "snapshot the disk" stopped meaning anything for the same reason. A check
// with nothing to check does not belong in the suite.
vi.mock("../api.js", () => ({
  api: {
    listRevisions: vi.fn(),
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
  author: "operator",
  created_at: "2026-10-23T11:00:00Z",
  file_count: 10,
};

function arrange({ revisions = [REV_2, REV_1], files = [], contents = "" } = {}) {
  api.listRevisions.mockResolvedValue(revisions);
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
    expect(rows[1]).toHaveTextContent("operator");
    expect(rows[0]).toHaveTextContent("11");
    expect(rows[1]).toHaveTextContent("10");
  });

  it("explains why a five-step run leaves fewer than five revisions", async () => {
    arrange();
    render(<Revisions target={TARGET} />);

    // A run committing three revisions for five steps reads like a bug unless
    // the panel says that `rev` counts changes rather than steps.
    const hint = await screen.findByText(/only at the step boundaries/i);
    expect(hint).toHaveTextContent(/changed/i);
    expect(hint).toHaveTextContent(/operator/i);
  });

  it("says a target with no revisions cannot be run", async () => {
    arrange({ revisions: [] });
    render(<Revisions target={TARGET} />);

    // A target created in the portal has revision 1 from the moment it exists,
    // so an empty history is a broken target rather than a new one.
    expect(await screen.findByText(/No revisions yet/i)).toBeInTheDocument();
    expect(screen.getByText(/cannot be run/i)).toBeInTheDocument();
  });

  it("offers no way to write a revision from this panel", async () => {
    arrange();
    render(<Revisions target={TARGET} />);
    await screen.findByRole("button", { name: /^rev 2$/i });

    // Revisions are written by a run's ingest and by the story and config
    // editors. Displaying a tree must not be able to change one.
    expect(screen.queryByRole("button", { name: /snapshot/i })).not.toBeInTheDocument();
    expect(api.listRevisions).toHaveBeenCalledWith(TARGET.id);
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

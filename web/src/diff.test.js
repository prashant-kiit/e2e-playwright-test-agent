import { describe, expect, it } from "vitest";
import { lineDiff } from "./diff.js";

// "same" -> s, "added" -> a, "removed" -> r, so a whole diff's shape reads as
// one short string in the assertion.
const kinds = (d) => d.map((l) => l.kind[0]).join("");
const text = (d, kind) => d.filter((l) => l.kind === kind).map((l) => l.text);

describe("lineDiff", () => {
  it("reports unchanged lines as unchanged", () => {
    const d = lineDiff("a\nb\n", "a\nb\n");

    expect(kinds(d)).toBe("ss");
    expect(text(d, "same")).toEqual(["a", "b"]);
  });

  it("finds an inserted line without rewriting the lines around it", () => {
    // The whole point of a diff rather than two bodies side by side: a one
    // line insertion must read as one line, not as "everything after it
    // changed".
    const d = lineDiff("a\nc\n", "a\nb\nc\n");

    expect(kinds(d)).toBe("sas");
    expect(text(d, "added")).toEqual(["b"]);
    expect(text(d, "removed")).toEqual([]);
  });

  it("finds a deleted line", () => {
    const d = lineDiff("a\nb\nc\n", "a\nc\n");

    expect(kinds(d)).toBe("srs");
    expect(text(d, "removed")).toEqual(["b"]);
  });

  it("reports a replaced line as a removal and an addition", () => {
    const d = lineDiff("keep\nold\nkeep2\n", "keep\nnew\nkeep2\n");

    expect(text(d, "removed")).toEqual(["old"]);
    expect(text(d, "added")).toEqual(["new"]);
    expect(text(d, "same")).toEqual(["keep", "keep2"]);
  });

  it("handles a prompt that was empty before", () => {
    const d = lineDiff("", "a line\n");

    expect(text(d, "added")).toEqual(["a line"]);
  });

  it("does not report a trailing newline as a changed line", () => {
    // Prompt bodies are files and end with a newline; splitting naively gives
    // a phantom empty last line and every diff would show a change at the end.
    const d = lineDiff("a\n", "a");

    expect(text(d, "added")).toEqual([]);
    expect(text(d, "removed")).toEqual([]);
  });

  it("keeps a blank line inside a body as a real line", () => {
    // A blank line between paragraphs is content in a prompt, unlike the
    // trailing one above.
    const d = lineDiff("a\n\nb\n", "a\n\nb\nc\n");

    expect(text(d, "same")).toEqual(["a", "", "b"]);
    expect(text(d, "added")).toEqual(["c"]);
  });
});

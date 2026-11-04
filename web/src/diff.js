/**
 * A line diff, for showing what a customer changed between two prompt
 * revisions (#39).
 *
 * Its own module, and hand-written rather than a dependency. The question
 * "what changed between revision 3 and revision 4 of my prompt" is one
 * function over two strings, and the portal has no other use for a diff -- so
 * a library here would be a build-size and supply-chain cost carried for one
 * caller. The same reasoning as `app/auth.py` hashing with PBKDF2 from the
 * standard library rather than adding passlib.
 *
 * The algorithm is the textbook LCS table. Prompt bodies are a few dozen lines
 * and the diff runs when a customer clicks one revision, so the O(n*m) table
 * is the right trade for code anyone can check by reading it: a smarter
 * algorithm (Myers) is faster and nobody would be able to tell here.
 */

/**
 * Split a body into lines the way a reader sees them.
 *
 * A prompt body is a file and ends with a newline, so a plain `split("\n")`
 * yields a phantom empty final element and every diff of two such bodies
 * would show a change at the end. Only that one trailing newline is dropped --
 * a blank line *inside* a body is a paragraph break, which is content.
 */
function lines(body) {
  const text = body ?? "";
  if (text === "") return [];
  const split = text.split("\n");
  if (split[split.length - 1] === "") split.pop();
  return split;
}

/**
 * The diff of two bodies, as a flat list of `{ kind, text }` in reading order.
 *
 * `kind` is "same", "added" or "removed" -- added and removed meaning present
 * in `after` and in `before` respectively. A replaced line comes back as a
 * removal followed by an addition, which is what a reader of a prompt wants to
 * see: the old wording and the new one, adjacent.
 */
export function lineDiff(before, after) {
  const a = lines(before);
  const b = lines(after);

  // table[i][j] = length of the longest common subsequence of a[i:] and b[j:].
  const table = Array.from({ length: a.length + 1 }, () =>
    new Array(b.length + 1).fill(0),
  );
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      table[i][j] =
        a[i] === b[j]
          ? table[i + 1][j + 1] + 1
          : Math.max(table[i + 1][j], table[i][j + 1]);
    }
  }

  // Walk the table forwards, which is what puts the result in reading order.
  const out = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      out.push({ kind: "same", text: a[i] });
      i++;
      j++;
    } else if (table[i + 1][j] >= table[i][j + 1]) {
      // Dropping a[i] keeps at least as much in common, so it was removed.
      out.push({ kind: "removed", text: a[i] });
      i++;
    } else {
      out.push({ kind: "added", text: b[j] });
      j++;
    }
  }
  while (i < a.length) out.push({ kind: "removed", text: a[i++] });
  while (j < b.length) out.push({ kind: "added", text: b[j++] });
  return out;
}

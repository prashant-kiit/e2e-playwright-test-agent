import { useState } from "react";
import { Field } from "./components.jsx";

// One definition of what a target's configuration is, for the two forms that
// write it.
//
// The server has exactly one: target_config.CLEANERS, the map every write path
// goes through. Two portal forms -- create a target, edit a target -- used to
// spell the same five fields out twice, which is how a field added on the
// server reaches one form and not the other. They render from this list
// instead. `hint` is the parenthetical the edit form adds, because an operator
// changing a live target wants to know which values are tracked in the tree and
// which only reach the agent's prompt; the create form keeps the labels short.

export const CONFIG_FIELDS = [
  {
    key: "base_url",
    label: "Base URL",
    hint: "inlined into the generated Playwright config",
    placeholder: "https://my-app.example.com",
    required: true,
  },
  {
    key: "target_repo",
    label: "Target repo (owner/repo)",
    hint: "receives the delivered tests",
    placeholder: "owner/repo",
    required: true,
  },
  { key: "target_branch", label: "Target branch", required: true },
  {
    key: "locators",
    label: "Locator convention",
    hint: "injected into the agent's prompt",
    placeholder: "data-testid attributes: page.getByTestId('…')",
  },
  {
    key: "agent_notes",
    label: "Agent notes, one per line",
    hint: "injected into the agent's prompt",
    lines: true,
  },
];

export function ConfigFields({ form, set, notes, setNotes, hints = false, rows = 3 }) {
  return CONFIG_FIELDS.map((field) => (
    <Field key={field.key} label={hints && field.hint ? `${field.label} (${field.hint})` : field.label}>
      {field.lines ? (
        <textarea rows={rows} value={notes} onChange={(e) => setNotes(e.target.value)} />
      ) : (
        <input
          value={form[field.key]}
          onChange={set(field.key)}
          placeholder={field.placeholder}
          required={field.required}
        />
      )}
    </Field>
  ));
}

// A form over a flat object, with one change handler per key.
export function useFields(initial) {
  const [form, setForm] = useState(initial);
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });
  return [form, set, setForm];
}

// The notes textarea is one note per line; the row stores a list. Blank lines
// are dropped rather than stored as empty notes the agent would read.
export function noteLines(text) {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

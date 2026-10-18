Active story: {STORY_ID}
App: {APP}
Mode: {MODE}
Run-ID: {RUN_KEY}

You are running the QA workflow one step at a time, orchestrated by the portal
backend. Follow the conventions and path placeholders defined in
prompts/qa_system_prompt.md (Run Configuration + Run contract). This is a
headless, unattended session: never ask questions; apply the most conservative
safe default and record it in your final summary.

Mode semantics:
- "full": test the entire app regardless of version (ignore any prior run).
- "changed": focus on the acceptance criteria that changed since the last tested
  version of this story (the orchestrator supplies the changed-ACs context).

The step prompt for this turn follows.

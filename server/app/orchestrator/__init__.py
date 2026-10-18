"""The run orchestrator: drives the 5 pipeline steps one at a time, checkpoints
after each (step-level resume), and relays live log lines.

The actual per-step work is behind the Runner protocol so the driver can be
tested with a FakeRunner (no Claude Code, no tokens) while the real ClaudeRunner
shells out to the `claude` CLI.
"""

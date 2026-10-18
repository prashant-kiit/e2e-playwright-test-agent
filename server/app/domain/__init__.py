"""Pure domain logic for QA runs: step order, status transitions, lease math.

Nothing in this package touches the database, the filesystem, or Claude Code.
It is all deterministic and unit-tested without any external services, which is
exactly the part of the system worth TDD-ing (the agent itself is not).
"""

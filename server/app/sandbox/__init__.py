"""Everything that happens *around* a run: building its worktree and removing it.

P4 moves these into a container-per-run. They are plain functions composed by
the launcher precisely so that move is a change of *where* they run and not of
*what* they do -- nothing in here may assume it is executing in the API process.
"""

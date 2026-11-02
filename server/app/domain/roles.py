"""A user's role within their tenant.

Two roles, because P5 needs exactly one distinction: who may take a
tenant-admin action (approve a delivery, rotate the PAT, change quotas or
users) and who may not. A finer hierarchy would be columns nothing reads.

`(str, Enum)` rather than `StrEnum` for the same reason the other domain enums
are (see app/models._enum_col and the UP042 note in pyproject.toml): the column
is a VARCHAR storing the member *value*, and the two bases do not stringify the
same way.
"""

from __future__ import annotations

from enum import Enum


class UserRole(str, Enum):
    MEMBER = "member"
    ADMIN = "admin"

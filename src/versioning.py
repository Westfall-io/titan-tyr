"""Semver helpers — caller-supplied MAJOR.MINOR.PATCH with optional -rcN suffix."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import total_ordering

VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-(rc\d+))?$")
RC_RE = re.compile(r"^rc(\d+)$")


class InvalidVersion(ValueError):
    """Raised when a version string does not match the supported grammar."""


@total_ordering
@dataclass(frozen=True)
class Version:
    major: int
    minor: int
    patch: int
    prerelease: str | None = None  # 'rcN' or None

    @classmethod
    def parse(cls, s: str, *, allow_prerelease: bool = True) -> Version:
        match = VERSION_RE.match(s)
        if not match:
            raise InvalidVersion(
                f"Version {s!r} does not match MAJOR.MINOR.PATCH[-rcN]"
            )
        major, minor, patch, pre = match.groups()
        if pre is not None and not allow_prerelease:
            raise InvalidVersion(
                f"Version {s!r} carries a pre-release suffix where one is not allowed"
            )
        return cls(int(major), int(minor), int(patch), pre)

    def __str__(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        return f"{base}-{self.prerelease}" if self.prerelease else base

    @property
    def is_prerelease(self) -> bool:
        return self.prerelease is not None

    def stable(self) -> Version:
        """Return the equivalent stable version with any prerelease stripped."""
        return Version(self.major, self.minor, self.patch, None)

    def _sort_key(self) -> tuple:
        # Stable (None) > any prerelease at the same triple.
        # Within prereleases, compare numerically by rcN.
        if self.prerelease is None:
            pre_key: tuple[int, int] = (1, 0)
        else:
            m = RC_RE.match(self.prerelease)
            # parser guarantees rcN; defensive fallback keeps the type consistent
            n = int(m.group(1)) if m else 0
            pre_key = (0, n)
        return (self.major, self.minor, self.patch, pre_key)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self._sort_key() < other._sort_key()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self._sort_key() == other._sort_key()

    def __hash__(self) -> int:
        return hash(self._sort_key())

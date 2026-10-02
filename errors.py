"""One error type for everything the caller can fix.

Every error says three things: what went wrong, where (row and column, or the
spec key), and what to do next. Tools turn it into JSON; nothing is raised to
Hermes.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class ChartError(Exception):
    """A problem the caller can fix by changing the input."""

    def __init__(self, code: str, message: str, *, where: str = "", fix: str = "",
                 example: Optional[Any] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.where = where
        self.fix = fix
        self.example = example

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"code": self.code, "message": self.message}
        if self.where:
            out["where"] = self.where
        if self.fix:
            out["fix"] = self.fix
        if self.example is not None:
            out["example"] = self.example
        return out

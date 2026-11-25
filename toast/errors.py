# SPDX-FileCopyrightText: 2026 varomix
#
# SPDX-License-Identifier: GPL-2.0-or-later


class ToastError(Exception):
    """An error in user code, with the 1-based line it refers to (None if unknown)."""

    def __init__(self, message, line=None, source=None):
        super().__init__(message)
        self.message = message
        self.line = line
        # Library the error is in (e.g. "toast_lib.shapes"), None for the node's own code.
        self.source = source

    def __str__(self):
        where = f"{self.source} " if self.source else ""
        if self.line is None:
            return f"{where}{self.message}" if where else self.message
        return f"{where}line {self.line}: {self.message}"


class ToastBuildError(Exception):
    """The C++ compiler rejected generated code. A Toast bug, not a user error."""

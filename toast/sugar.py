# SPDX-FileCopyrightText: 2026 varomix
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Rewrite Toast's ``@`` attribute sugar into plain Python, before ``ast.parse``.

``@position`` becomes ``_A.position``. The rewrite works on the token stream, one line at a time,
so line numbers stay the same and errors point at the user's line. Types come from Python
annotations (``@height: float = n``), not from prefixes. ``@`` as matrix multiplication and
decorators are not part of Toast.
"""

import io
import tokenize

from .errors import ToastError

ATTR_OBJECT = "_A"


def desugar(source):
    """Return ``source`` with ``@`` attributes rewritten. Raises ToastError on bad syntax."""
    lines = source.splitlines(keepends=True)
    # (row, start_col, end_col, replacement), row is 1-based.
    edits = []

    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError) as ex:
        line = getattr(ex, "lineno", None)
        if line is None and len(ex.args) > 1 and isinstance(ex.args[1], tuple):
            line = ex.args[1][0]
        raise ToastError(f"syntax error: {ex.args[0]}", line) from None

    for k, tok in enumerate(tokens):
        if tok.type != tokenize.OP or tok.string != "@":
            continue
        row, col = tok.start
        nxt = tokens[k + 1] if k + 1 < len(tokens) else None
        if nxt is None or nxt.type != tokenize.NAME or nxt.start != tok.end:
            raise ToastError(
                "'@' must be followed directly by an attribute name, like @position "
                "(matrix multiplication with '@' is not supported)",
                row,
            )
        prev = tokens[k - 1] if k > 0 else None
        if prev is not None and prev.type == tokenize.NAME and prev.end == tok.start:
            raise ToastError(
                f"'{prev.string}@{nxt.string}': type prefixes are not used in Toast, annotate "
                f"the type instead, like @{nxt.string}: vec3 = ...",
                row,
            )
        edits.append((row, col, nxt.end[1], f"{ATTR_OBJECT}.{nxt.string}"))

    # Apply right to left per line so earlier columns stay valid.
    for row, start, end, text in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        line = lines[row - 1]
        lines[row - 1] = line[:start] + text + line[end:]
    return "".join(lines)

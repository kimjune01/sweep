"""Backward-compat shim — the CLI lives in sweep.cli now.

The `sweep` console script entry in pyproject.toml points here; this file
just re-exports `app` from sweep.cli so the entry stays stable across
the refactor.
"""

from __future__ import annotations

from sweep.cli import app, main

__all__ = ["app", "main"]


if __name__ == "__main__":
    main()

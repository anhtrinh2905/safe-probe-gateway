"""safe_probe -- a probing tool that can only reach the gateway.

Stdlib only, on purpose: this package is the component being kept honest, so its
reachable surface should be readable end to end. See AGENTS.md.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"

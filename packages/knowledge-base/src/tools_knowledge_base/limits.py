"""Bounds shared by the settings and the operations."""

# A store asks for one row past the page; unbounded, that overflows LanceDB's int64.
MAX_LIMIT = 1000

"""Fetchers: one module per ATS, each exposing `fetch(company, client)`.

Importing this package registers every built fetcher in `tracker.fetchers.base`.
"""

from tracker.fetchers import ashby, greenhouse, lever, workday  # noqa: F401  (registers fetchers)
from tracker.fetchers.base import FetchError, get_fetcher

__all__ = ["FetchError", "get_fetcher"]

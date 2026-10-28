"""Fetchers: one module per ATS, each exposing `fetch(company, client)`.

Importing this package registers every built fetcher in `tracker.fetchers.base`.
"""

from tracker.fetchers import (  # noqa: F401  (registers fetchers)
    ashby,
    eightfold,
    greenhouse,
    lever,
    oracle_hcm,
    smartrecruiters,
    workday,
)
from tracker.fetchers.base import FetchError, get_fetcher
from tracker.fetchers.custom import (  # noqa: F401  (registers fetchers)
    amazon,
    amd,
    apple,
    atlassian,
    barclays,
    goldman,
    google,
    rippling,
)

__all__ = ["FetchError", "get_fetcher"]

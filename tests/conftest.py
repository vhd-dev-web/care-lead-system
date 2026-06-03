"""Pytest fixtures that keep the test suite hermetic.

We had an incident where a test that called run_pipeline without
sync_google=False auto-enabled the Google Sheets sync because the
parent shell exported VHD_GOOGLE_SPREADSHEET_ID. The test then wrote
its fixture into the real Clay Queue tab and overwrote production data.

This conftest scrubs every environment variable that could let a test
reach an external service. Tests that legitimately need credentials
must set them explicitly via monkeypatch.
"""

from __future__ import annotations

import os

import pytest


_DANGEROUS_ENV_VARS = (
    "VHD_GOOGLE_SPREADSHEET_ID",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GOOGLE_SERVICE_ACCOUNT_FILE",
    "BRAVE_SEARCH_API_KEY",
    "GOOGLE_CSE_API_KEY",
    "GOOGLE_CSE_ID",
    "SERPER_API_KEY",
    "FIRECRAWL_API_KEY",
    "TAVILY_API_KEY",
    "CLAY_API_KEY",
)


@pytest.fixture(autouse=True)
def scrub_external_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove credentials and sheet IDs from os.environ for every test.

    autouse=True applies this to every test in the suite without each
    test having to opt in. monkeypatch restores the original values
    after the test finishes.
    """
    for name in _DANGEROUS_ENV_VARS:
        if name in os.environ:
            monkeypatch.delenv(name, raising=False)

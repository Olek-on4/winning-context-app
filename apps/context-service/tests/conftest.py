"""Tests run without a model: the suite pins the deterministic planner.

A live model would make the golden answers depend on which weights happen to be pulled.
Set `ETYT_TEST_MODEL=1` to exercise the model path deliberately.
"""

from __future__ import annotations

import os

import pytest

from retrieval import planner


@pytest.fixture(autouse=True)
def offline_model(monkeypatch: pytest.MonkeyPatch) -> None:
    if os.getenv("ETYT_TEST_MODEL") == "1":
        return

    def unavailable(question: str):
        raise RuntimeError("no model in tests")

    monkeypatch.setattr(planner, "_from_model", unavailable)

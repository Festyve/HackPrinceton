"""Shared fixtures. Everything runs offline; no test needs a key or the network."""

from __future__ import annotations

from pathlib import Path

import pytest

from alibi.episode import EpisodePaths, create_episode
from alibi.evidence.store import EvidenceStore

# Development seeds: hand-inspected while building. The declared benchmark test seeds
# live in docs/evaluation-config.json and are not used for tuning.
DEV_SEED = 3


@pytest.fixture(scope="session")
def roots(tmp_path_factory) -> tuple[Path, Path]:
    base = tmp_path_factory.mktemp("alibi")
    return base / "runs", base / "sealed"


@pytest.fixture(scope="session")
def make_episode(roots):
    cache: dict[tuple[int, str], EpisodePaths] = {}

    def _make(seed: int, variant: str) -> EpisodePaths:
        key = (seed, variant)
        if key not in cache:
            cache[key] = create_episode(seed=seed, variant=variant, runs_dir=roots[0], sealed_dir=roots[1],
                                        episode_id=f"t-{variant.replace('_', '-')}-{seed}")
        return cache[key]

    return _make


@pytest.fixture(scope="session")
def coverup(make_episode) -> EpisodePaths:
    return make_episode(DEV_SEED, "incident_coverup")


@pytest.fixture(scope="session")
def plain(make_episode) -> EpisodePaths:
    return make_episode(DEV_SEED, "incident_plain")


@pytest.fixture()
def store_for():
    opened: list[EvidenceStore] = []

    def _open(paths: EpisodePaths) -> EvidenceStore:
        st = EvidenceStore(paths.db)
        opened.append(st)
        return st

    yield _open
    for st in opened:
        st.close()

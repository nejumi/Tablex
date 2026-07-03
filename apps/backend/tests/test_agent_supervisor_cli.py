from __future__ import annotations

import threading
import time
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from tabular_harness.models.entities import Base
from tabular_harness.services.artifacts import LocalArtifactStore
from tabular_harness.worker.agent_supervisor_cli import run_agent_session_supervisor_loop


def test_agent_supervisor_loop_once_runs_recovery_with_stable_owner(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    calls: list[dict[str, object]] = []

    def fake_supervisor_runner(*args: object, **kwargs: object) -> list[threading.Thread]:
        del args
        calls.append(kwargs)
        return []

    run_agent_session_supervisor_loop(
        session_factory,
        store,
        once=True,
        interval_seconds=0.01,
        lease_owner_id="dedicated-supervisor:test",
        agent_model="codex-test-model",
        supervisor_runner=fake_supervisor_runner,
    )

    assert len(calls) == 1
    assert calls[0]["lease_owner_id"] == "dedicated-supervisor:test"
    assert calls[0]["agent_model"] == "codex-test-model"


def test_agent_supervisor_loop_respects_stop_event(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    stop_event = threading.Event()
    calls: list[str] = []

    def fake_supervisor_runner(*args: object, **kwargs: object) -> list[threading.Thread]:
        del args
        calls.append(str(kwargs.get("lease_owner_id")))
        if len(calls) >= 2:
            stop_event.set()
        return []

    run_agent_session_supervisor_loop(
        session_factory,
        store,
        interval_seconds=0.01,
        lease_owner_id="dedicated-supervisor:stop-test",
        stop_event=stop_event,
        supervisor_runner=fake_supervisor_runner,
    )

    assert len(calls) >= 2
    assert all(call == "dedicated-supervisor:stop-test" for call in calls)
    assert stop_event.is_set()


def test_agent_supervisor_loop_waits_between_scans(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    stop_event = threading.Event()
    call_times: list[float] = []

    def fake_supervisor_runner(*args: object, **kwargs: object) -> list[threading.Thread]:
        del args, kwargs
        call_times.append(time.monotonic())
        if len(call_times) >= 2:
            stop_event.set()
        return []

    run_agent_session_supervisor_loop(
        session_factory,
        store,
        interval_seconds=0.03,
        stop_event=stop_event,
        supervisor_runner=fake_supervisor_runner,
    )

    assert len(call_times) == 2
    assert call_times[1] - call_times[0] >= 0.02

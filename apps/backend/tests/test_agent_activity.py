from __future__ import annotations

from tabular_harness.api.routes import suppress_resolved_agent_availability_workers


def test_suppress_resolved_agent_availability_workers_hides_recovery_for_live_session() -> None:
    workers = [
        {"worker_id": "main-agent-session", "status": "running"},
        {"worker_id": "agent-availability-ags_live-turn_recovery", "status": "recovering"},
        {"worker_id": "agent-availability-ags_live-turn_start_silence", "status": "recovering"},
        {"worker_id": "agent-availability-ags_other-turn_recovery", "status": "recovering"},
        {"worker_id": "agent-availability-ags_live-runner_unavailable", "status": "waiting"},
    ]

    filtered = suppress_resolved_agent_availability_workers(workers, session_id="ags_live")
    worker_ids = [worker["worker_id"] for worker in filtered]

    assert worker_ids == [
        "main-agent-session",
        "agent-availability-ags_other-turn_recovery",
        "agent-availability-ags_live-runner_unavailable",
    ]

from tabular_harness.services.codex_transcript import build_codex_cli_transcript, parse_codex_jsonl


def test_parse_codex_jsonl_ignores_non_json_noise() -> None:
    stdout = "\n".join(
        [
            "noise before json",
            '{"type":"thread.started","thread_id":"t_001"}',
            '{"type":"item.completed","item":{"type":"agent_message","text":"ok"}}',
            "not json",
            '{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":2}}',
        ]
    )

    events = parse_codex_jsonl(stdout)

    assert [event["type"] for event in events] == ["thread.started", "item.completed", "turn.completed"]
    assert events[1]["item"]["text"] == "ok"


def test_build_codex_cli_transcript_keeps_events_and_stdio_tails() -> None:
    transcript = build_codex_cli_transcript(
        status="succeeded",
        command="codex exec --json -",
        timeout_seconds=90,
        exit_code=0,
        duration_ms=1234,
        stdout='{"type":"item.completed","item":{"type":"agent_message","text":"hello"}}\n',
        stderr="warning",
    )

    assert transcript["schema_version"] == "codex_cli_transcript.v1"
    assert transcript["event_count"] == 1
    assert transcript["events"][0]["item"]["text"] == "hello"
    assert transcript["stderr_tail"] == "warning"

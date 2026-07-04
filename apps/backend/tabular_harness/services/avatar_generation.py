from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tabular_harness.agent.runners import CODEX_HARNESS_CONFIG_ARGS


class AvatarGenerationError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class AvatarCandidate:
    id: str
    data_url: str
    model: str
    revised_prompt: str | None = None


def generate_user_avatar_candidates(
    *,
    prompt: str,
    count: int,
    user: str | None = None,
) -> list[AvatarCandidate]:
    normalized_prompt = prompt.strip()
    if not normalized_prompt:
        raise AvatarGenerationError("Avatar prompt is required.", status_code=400)
    count = max(1, min(4, count))
    provider = os.getenv("TABLEX_AVATAR_PROVIDER", "auto").strip().lower() or "auto"
    if provider not in {"auto", "codex", "openai"}:
        raise AvatarGenerationError(
            "TABLEX_AVATAR_PROVIDER must be one of: auto, codex, openai.",
            status_code=500,
        )

    errors: list[str] = []
    if provider in {"auto", "codex"}:
        try:
            return generate_with_codex_cli(prompt=normalized_prompt, count=count)
        except AvatarGenerationError as exc:
            if provider == "codex":
                raise
            errors.append(str(exc))

    if provider in {"auto", "openai"}:
        try:
            return generate_with_openai_api(prompt=normalized_prompt, count=count, user=user)
        except AvatarGenerationError as exc:
            if provider == "openai":
                raise
            errors.append(str(exc))

    suffix = f" Details: {'; '.join(errors)}" if errors else ""
    raise AvatarGenerationError(
        "No avatar image generation backend is available. Codex CLI image generation is preferred; "
        "OPENAI_API_KEY is only needed when TABLEX_AVATAR_PROVIDER=openai or Codex CLI is unavailable."
        + suffix,
        status_code=503,
    )


def generate_with_openai_api(
    *,
    prompt: str,
    count: int,
    user: str | None = None,
) -> list[AvatarCandidate]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise AvatarGenerationError(
            "OPENAI_API_KEY is not configured for the OpenAI API avatar provider.",
            status_code=503,
        )
    model = os.getenv("TABLEX_AVATAR_IMAGE_MODEL", "gpt-image-2").strip() or "gpt-image-2"
    output_format = os.getenv("TABLEX_AVATAR_IMAGE_FORMAT", "png").strip().lower() or "png"
    quality = os.getenv("TABLEX_AVATAR_IMAGE_QUALITY", "low").strip().lower() or "low"
    payload: dict[str, Any] = {
        "model": model,
        "prompt": avatar_prompt(prompt),
        "n": count,
        "size": "1024x1024",
        "quality": quality,
        "output_format": output_format,
    }
    if user:
        payload["user"] = user[:64]

    request = urllib.request.Request(
        "https://api.openai.com/v1/images/generations",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
            body = response.read()
    except urllib.error.HTTPError as exc:
        raise AvatarGenerationError(openai_error_message(exc), status_code=exc.code) from exc
    except urllib.error.URLError as exc:
        raise AvatarGenerationError("Image generation request failed before OpenAI returned a response.") from exc

    try:
        data = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise AvatarGenerationError("Image generation returned an invalid response.") from exc

    candidates: list[AvatarCandidate] = []
    for index, item in enumerate(data.get("data", [])):
        b64_json = item.get("b64_json")
        if not isinstance(b64_json, str) or not valid_base64(b64_json):
            continue
        candidates.append(
            AvatarCandidate(
                id=f"avatar_candidate_{index + 1}",
                data_url=f"data:image/{output_format};base64,{b64_json}",
                model=model,
                revised_prompt=item.get("revised_prompt") if isinstance(item.get("revised_prompt"), str) else None,
            )
        )
    if not candidates:
        raise AvatarGenerationError("Image generation returned no usable avatar candidates.")
    return candidates


def generate_with_codex_cli(*, prompt: str, count: int) -> list[AvatarCandidate]:
    codex = shutil.which("codex")
    if not codex:
        raise AvatarGenerationError("Codex CLI is not available on PATH for avatar generation.", status_code=503)

    timeout = codex_avatar_timeout()
    with tempfile.TemporaryDirectory(prefix="tablex_avatar_") as tmp:
        workdir = Path(tmp)
        result_path = workdir / "result.json"
        command = [
            codex,
            "exec",
            *CODEX_HARNESS_CONFIG_ARGS,
            "--cd",
            str(workdir),
            "--skip-git-repo-check",
            "--sandbox",
            "workspace-write",
            "--output-last-message",
            str(result_path),
        ]
        model = os.getenv("TABLEX_CODEX_AVATAR_MODEL", "").strip()
        if model:
            command.extend(["--model", model])
        command.append(codex_avatar_task_prompt(prompt=prompt, count=count))

        try:
            completed = subprocess.run(
                command,
                cwd=workdir,
                capture_output=True,
                check=False,
                stdin=subprocess.DEVNULL,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise AvatarGenerationError(
                f"Codex avatar generation timed out after {timeout} seconds.",
                status_code=504,
            ) from exc
        except OSError as exc:
            raise AvatarGenerationError("Codex avatar generation could not be started.", status_code=503) from exc

        if completed.returncode != 0:
            detail = compact_process_output(completed.stderr or completed.stdout)
            raise AvatarGenerationError(
                f"Codex avatar generation failed.{f' {detail}' if detail else ''}",
                status_code=502,
            )

        files, revised_prompt = codex_avatar_result_files(result_path)
        if not files:
            files = [path.name for path in sorted(workdir.glob("candidate_*.png"))]

        candidates: list[AvatarCandidate] = []
        for index, filename in enumerate(files[:count], start=1):
            path = safe_child_file(workdir, filename)
            if path is None or not path.is_file():
                continue
            data_url = image_file_to_data_url(path)
            if data_url is None:
                continue
            candidates.append(
                AvatarCandidate(
                    id=f"avatar_candidate_{index}",
                    data_url=data_url,
                    model="codex-cli:gpt-image-2",
                    revised_prompt=revised_prompt,
                )
            )

        if not candidates:
            raise AvatarGenerationError("Codex avatar generation returned no usable image files.", status_code=502)
        return candidates


def codex_avatar_task_prompt(*, prompt: str, count: int) -> str:
    file_list = [f"candidate_{index}.png" for index in range(1, count + 1)]
    return "\n".join(
        [
            "Use the built-in $imagegen capability to generate user avatar candidates for Tablex.",
            "This is a constrained asset-generation task. Work only in the current temporary directory.",
            "Do not read secrets, connector credentials, .env files, project data, or unrelated repository files.",
            f"Generate exactly {count} square PNG image file(s): {', '.join(file_list)}.",
            "Each candidate should work as a small chat/profile avatar: centered subject, friendly, polished, no logo, no watermark, no UI screenshot.",
            "Avoid text, letters, numbers, spreadsheet cell labels, and brand marks unless the user explicitly asked for them.",
            "If a transparent background is practical, use the built-in image generation path and local chroma-key cleanup; otherwise use a clean simple background.",
            "Keep only the requested candidate PNG files in the current directory.",
            "Final response must be only valid JSON with this shape:",
            json.dumps({"files": file_list, "revised_prompt": "short prompt summary"}, ensure_ascii=True),
            "User avatar direction:",
            prompt,
        ]
    )


def codex_avatar_timeout() -> int:
    raw = os.getenv("TABLEX_CODEX_AVATAR_TIMEOUT_SECONDS", "480").strip()
    try:
        timeout = int(raw)
    except ValueError:
        timeout = 480
    return max(30, min(1800, timeout))


def codex_avatar_result_files(result_path: Path) -> tuple[list[str], str | None]:
    if not result_path.exists():
        return [], None
    raw = result_path.read_text(encoding="utf-8", errors="replace").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw.removeprefix("json").strip()
    if not raw.startswith("{"):
        start = raw.find("{")
        end = raw.rfind("}")
        raw = raw[start : end + 1] if start != -1 and end != -1 and end > start else raw
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return [], None
    if not isinstance(payload, dict):
        return [], None
    files = payload.get("files")
    revised_prompt = payload.get("revised_prompt")
    return (
        [item for item in files if isinstance(item, str)] if isinstance(files, list) else [],
        revised_prompt if isinstance(revised_prompt, str) else None,
    )


def safe_child_file(parent: Path, filename: str) -> Path | None:
    candidate = (parent / Path(filename).name).resolve()
    try:
        candidate.relative_to(parent.resolve())
    except ValueError:
        return None
    return candidate


def image_file_to_data_url(path: Path) -> str | None:
    data = path.read_bytes()
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        media_type = "image/png"
    elif data.startswith(b"\xff\xd8\xff"):
        media_type = "image/jpeg"
    elif data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        media_type = "image/webp"
    else:
        return None
    return f"data:{media_type};base64,{base64.b64encode(data).decode('ascii')}"


def compact_process_output(value: str, *, limit: int = 600) -> str:
    text = " ".join(value.split())
    return text[:limit]


def avatar_prompt(user_prompt: str) -> str:
    return "\n".join(
        [
            "Create a square user avatar icon for Tablex, a tabular AI agent workbench.",
            "The image should read clearly at small chat-avatar sizes, with a centered subject, friendly professional mood, and no text.",
            "Avoid logos, brand names, UI screenshots, watermarks, or spreadsheet data.",
            "User direction:",
            user_prompt,
        ]
    )


def valid_base64(value: str) -> bool:
    try:
        base64.b64decode(value, validate=True)
    except ValueError:
        return False
    return True


def openai_error_message(exc: urllib.error.HTTPError) -> str:
    try:
        payload = json.loads(exc.read().decode("utf-8"))
    except Exception:
        payload = {}
    error = payload.get("error") if isinstance(payload, dict) else None
    message = error.get("message") if isinstance(error, dict) else None
    if isinstance(message, str) and message:
        return message
    return "OpenAI image generation request failed."

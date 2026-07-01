from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


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
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise AvatarGenerationError(
            "OPENAI_API_KEY is not configured for image generation.",
            status_code=503,
        )
    normalized_prompt = prompt.strip()
    if not normalized_prompt:
        raise AvatarGenerationError("Avatar prompt is required.", status_code=400)
    count = max(1, min(4, count))
    model = os.getenv("TABLEX_AVATAR_IMAGE_MODEL", "gpt-image-2").strip() or "gpt-image-2"
    output_format = os.getenv("TABLEX_AVATAR_IMAGE_FORMAT", "png").strip().lower() or "png"
    quality = os.getenv("TABLEX_AVATAR_IMAGE_QUALITY", "low").strip().lower() or "low"
    payload: dict[str, Any] = {
        "model": model,
        "prompt": avatar_prompt(normalized_prompt),
        "n": count,
        "size": "1024x1024",
        "quality": quality,
        "output_format": output_format,
        "background": "transparent",
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

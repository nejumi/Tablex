from __future__ import annotations

import json
from typing import Any


def dumps_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def loads_json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


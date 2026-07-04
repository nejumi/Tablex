from __future__ import annotations


def normalized_locale(locale: str | None) -> str:
    return (locale or "").strip().lower().replace("_", "-")


def locale_language(locale: str | None) -> str:
    normalized = normalized_locale(locale)
    if not normalized:
        return ""
    if "japanese" in normalized or "日本語" in normalized:
        return "ja"
    return normalized.split("-", 1)[0]


def locale_is_japanese(locale: str | None) -> bool:
    return locale_language(locale) == "ja"

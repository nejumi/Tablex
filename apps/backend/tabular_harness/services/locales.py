from __future__ import annotations


def normalized_locale(locale: str | None) -> str:
    return (locale or "").strip().lower().replace("_", "-")


def locale_language(locale: str | None) -> str:
    normalized = normalized_locale(locale)
    if not normalized:
        return ""
    if normalized == "japanese" or normalized == "日本語" or normalized.startswith("日本語"):
        return "ja"
    return normalized.split("-", 1)[0]


def locale_is_japanese(locale: str | None) -> bool:
    return locale_language(locale) == "ja"

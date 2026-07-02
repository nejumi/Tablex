from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tabular_harness.core.ids import new_id
from tabular_harness.models.entities import AuthSession, User, utc_now

PBKDF2_ITERATIONS = 210_000


@dataclass(frozen=True)
class AuthToken:
    token: str
    session: AuthSession


def create_user(
    db: Session,
    *,
    email: str,
    password: str,
    display_name: str | None = None,
    is_admin: bool = False,
) -> User:
    normalized_email = normalize_email(email)
    if not normalized_email:
        raise ValueError("Email is required.")
    password_errors = password_policy_errors(password)
    if password_errors:
        raise ValueError("Password must " + ", ".join(password_errors) + ".")
    existing = db.scalar(select(User).where(func.lower(User.email) == normalized_email.lower()))
    if existing is not None:
        raise ValueError("User already exists.")
    user = User(
        id=new_id("user"),
        email=normalized_email,
        display_name=display_name or normalized_email.split("@")[0],
        password_hash=hash_password(password),
        auth_provider="password",
        is_admin=is_admin,
    )
    db.add(user)
    db.flush()
    return user


def ensure_bootstrap_user(db: Session, *, email: str | None, password: str | None) -> User | None:
    if not email or not password:
        return None
    existing_count = int(db.scalar(select(func.count()).select_from(User)) or 0)
    existing = db.scalar(select(User).where(func.lower(User.email) == normalize_email(email).lower()))
    if existing is not None:
        return existing
    return create_user(db, email=email, password=password, is_admin=existing_count == 0)


def authenticate_password(db: Session, *, email: str, password: str) -> User | None:
    user = db.scalar(select(User).where(func.lower(User.email) == normalize_email(email).lower()))
    if user is None or not user.is_active or not user.password_hash:
        return None
    if not verify_password(password, user.password_hash):
        return None
    user.last_login_at = utc_now()
    return user


def create_auth_session(
    db: Session,
    *,
    user: User,
    session_days: int,
    user_agent: str | None,
    ip_address: str | None,
) -> AuthToken:
    token = secrets.token_urlsafe(48)
    session = AuthSession(
        id=new_id("sess"),
        user_id=user.id,
        session_token_hash=hash_session_token(token),
        expires_at=utc_now() + timedelta(days=max(1, session_days)),
        user_agent=user_agent,
        ip_address=ip_address,
    )
    db.add(session)
    db.flush()
    return AuthToken(token=token, session=session)


def user_for_session_token(db: Session, token: str | None) -> User | None:
    if not token:
        return None
    session = db.scalar(select(AuthSession).where(AuthSession.session_token_hash == hash_session_token(token)))
    if session is None or session.revoked_at is not None or session_expired(session.expires_at):
        return None
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        return None
    return user


def revoke_session_token(db: Session, token: str | None) -> None:
    if not token:
        return
    session = db.scalar(select(AuthSession).where(AuthSession.session_token_hash == hash_session_token(token)))
    if session is not None and session.revoked_at is None:
        session.revoked_at = utc_now()


def user_settings_payload(user: User) -> dict[str, Any]:
    return {
        "locale": user.locale,
        "requestedLocale": user.requested_locale,
        "dynamicLanguageRequest": user.dynamic_language_request,
        "displayTheme": user.display_theme,
        "interventionCountdownSeconds": user.intervention_countdown_seconds,
        "agentModel": user.agent_model,
        "utilityModel": user.utility_model,
        "chatSubmitShortcut": user.chat_submit_shortcut,
        "userAvatarDataUrl": user.user_avatar_data_url,
    }


def update_user_settings(user: User, settings: dict[str, Any]) -> User:
    if isinstance(settings.get("locale"), str):
        user.locale = clean_short_string(settings["locale"], fallback=user.locale, max_length=64)
    if isinstance(settings.get("requestedLocale"), str):
        user.requested_locale = clean_short_string(settings["requestedLocale"], fallback="", max_length=64)
    if isinstance(settings.get("dynamicLanguageRequest"), str):
        user.dynamic_language_request = str(settings["dynamicLanguageRequest"])[:4000]
    if settings.get("displayTheme") in {"light", "dark"}:
        user.display_theme = str(settings["displayTheme"])
    countdown = settings.get("interventionCountdownSeconds")
    if isinstance(countdown, int | float):
        user.intervention_countdown_seconds = min(300, max(0, int(countdown)))
    if isinstance(settings.get("agentModel"), str):
        user.agent_model = clean_short_string(settings["agentModel"], fallback="codex-default", max_length=120)
    if isinstance(settings.get("utilityModel"), str):
        user.utility_model = clean_short_string(settings["utilityModel"], fallback="utility-default", max_length=120)
    if settings.get("chatSubmitShortcut") in {"locale_default", "enter", "shift_enter"}:
        user.chat_submit_shortcut = str(settings["chatSubmitShortcut"])
    avatar = settings.get("userAvatarDataUrl")
    if avatar is None or (isinstance(avatar, str) and avatar.startswith("data:image/") and len(avatar) <= 2_000_000):
        user.user_avatar_data_url = avatar
    user.updated_at = utc_now()
    return user


def user_to_dict(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "auth_provider": user.auth_provider,
        "is_admin": user.is_admin,
        "settings": user_settings_payload(user),
        "created_at": user.created_at.isoformat(),
        "updated_at": user.updated_at.isoformat(),
    }


def normalize_email(email: str) -> str:
    return email.strip().lower()


def clean_short_string(value: str, *, fallback: str, max_length: int) -> str:
    cleaned = value.strip()[:max_length]
    return cleaned or fallback


def password_policy_errors(password: str) -> list[str]:
    errors: list[str] = []
    if len(password) < 10:
        errors.append("be at least 10 characters")
    if not any(character.islower() for character in password):
        errors.append("include a lowercase letter")
    if not any(character.isupper() for character in password):
        errors.append("include an uppercase letter")
    if not any(character.isdigit() for character in password):
        errors.append("include a digit")
    if not any(not character.isalnum() for character in password):
        errors.append("include a symbol")
    return errors


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        PBKDF2_ITERATIONS,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        algorithm, iteration_text, salt_text, digest_text = encoded_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iteration_text)
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_text.encode("ascii"))
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def session_expired(expires_at: datetime) -> bool:
    now = utc_now()
    if expires_at.tzinfo is None:
        now = now.replace(tzinfo=None)
    return expires_at <= now

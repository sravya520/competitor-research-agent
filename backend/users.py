import json
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, select, update

from backend import config, vault
from backend.db import session
from backend.models import ResearchJob, UsageDaily, User


@dataclass(frozen=True)
class UserInfo:
    id: int
    email: str
    name: str | None
    accepted_current_terms: bool
    onboarded: bool = False
    has_own_keys: bool = False
    free_runs_left: int = 0
    use_case: str | None = None
    team_size: str | None = None
    unlimited: bool = False  # on the allow list: runs on our keys with no limit


@dataclass(frozen=True)
class OwnKeys:
    gemini: str
    tavily: str


def _info(u: User) -> UserInfo:
    return UserInfo(
        id=u.id,
        email=u.email,
        name=u.name,
        accepted_current_terms=u.terms_version == config.LEGAL_VERSION,
        onboarded=u.onboarded_at is not None,
        has_own_keys=bool(u.gemini_key_enc and u.tavily_key_enc),
        free_runs_left=max(config.FREE_RUNS - (u.free_runs_used or 0), 0),
        use_case=u.use_case,
        team_size=u.team_size,
        unlimited=u.email.strip().lower() in config.UNLIMITED_EMAILS,
    )


def get_info(user_id: int) -> UserInfo | None:
    with session() as s:
        u = s.get(User, user_id)
        return _info(u) if u else None


def upsert_login(sub: str, email: str, name: str | None) -> UserInfo:
    """Create the user on first sign-in, refresh profile + last_login on later ones."""
    email = email.strip().lower()
    if not sub or not email:
        raise ValueError("Google sign-in did not return an id and email.")
    with session() as s:
        u = s.scalar(select(User).where(User.google_sub == sub))
        if u is None:
            u = User(google_sub=sub, email=email, name=name)
            s.add(u)
        else:
            u.email, u.name, u.last_login_at = email, name, datetime.now(timezone.utc)
        s.flush()
        return _info(u)


def accept_terms(user_id: int) -> None:
    with session() as s:
        u = s.get(User, user_id)
        u.terms_version = config.LEGAL_VERSION
        u.terms_accepted_at = datetime.now(timezone.utc)


# ---- Onboarding ----

def save_use_case(user_id: int, use_case: str) -> None:
    with session() as s:
        s.get(User, user_id).use_case = use_case[:120]


def save_team_size(user_id: int, team_size: str) -> None:
    with session() as s:
        s.get(User, user_id).team_size = team_size[:32]


def finish_onboarding(user_id: int) -> None:
    """Called when the user completes OR skips onboarding; either way they are not asked again."""
    with session() as s:
        u = s.get(User, user_id)
        if u.onboarded_at is None:
            u.onboarded_at = datetime.now(timezone.utc)


def save_team_invites(user_id: int, emails: list[str]) -> None:
    """Remember the teammates the user wants to invite. We do not email anyone yet."""
    clean = []
    for e in emails:
        e = e.strip().lower()
        if "@" in e and "." in e.split("@")[-1] and e not in clean:
            clean.append(e[:320])
    with session() as s:
        s.get(User, user_id).team_invites = json.dumps(clean[:10]) if clean else None


# ---- Own API keys ----

def save_keys(user_id: int, gemini: str, tavily: str) -> None:
    """Encrypt and store the user's keys. Raises vault.VaultUnavailable if encryption isn't set up."""
    g, t = vault.encrypt(gemini.strip()), vault.encrypt(tavily.strip())
    with session() as s:
        u = s.get(User, user_id)
        u.gemini_key_enc, u.tavily_key_enc = g, t


def clear_keys(user_id: int) -> None:
    with session() as s:
        u = s.get(User, user_id)
        u.gemini_key_enc = u.tavily_key_enc = None


def load_keys(user_id: int) -> OwnKeys | None:
    """The user's decrypted keys, or None if they have none (or they can no longer be read)."""
    with session() as s:
        u = s.get(User, user_id)
        if not (u and u.gemini_key_enc and u.tavily_key_enc):
            return None
        g, t = vault.decrypt(u.gemini_key_enc), vault.decrypt(u.tavily_key_enc)
    return OwnKeys(g, t) if g and t else None


def key_hints(user_id: int) -> tuple[str, str] | None:
    """('...abcd', '...wxyz') so the Account page can show WHICH keys are saved without revealing them."""
    keys = load_keys(user_id)
    return (f"…{keys.gemini[-4:]}", f"…{keys.tavily[-4:]}") if keys else None


# ---- Free run on our keys ----

def consume_free_run(user_id: int) -> bool:
    """Atomically spend one of the user's lifetime free runs. False if none are left."""
    with session() as s:
        bump = (
            update(User)
            .where(User.id == user_id, User.free_runs_used < config.FREE_RUNS)
            .values(free_runs_used=User.free_runs_used + 1)
        )
        return s.execute(bump).rowcount == 1


def refund_free_run(user_id: int) -> None:
    """Give the run back when the job could not even start (e.g. our quota was exhausted)."""
    with session() as s:
        s.execute(update(User).where(User.id == user_id, User.free_runs_used > 0).values(free_runs_used=User.free_runs_used - 1))


def delete_user(user_id: int) -> None:
    """Hard delete: the account, its usage rows and any in-progress job. Nothing else about the user is stored."""
    with session() as s:
        s.execute(delete(ResearchJob).where(ResearchJob.user_id == user_id))
        s.execute(delete(UsageDaily).where(UsageDaily.user_id == user_id))  # portable, no FK reliance
        s.execute(delete(User).where(User.id == user_id))

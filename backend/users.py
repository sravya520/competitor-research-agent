from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, select, update

from backend import config
from backend.db import session
from backend.models import ResearchJob, UsageDaily, User


@dataclass(frozen=True)
class UserInfo:
    id: int
    email: str
    name: str | None
    accepted_current_terms: bool
    onboarded: bool = False
    free_runs_left: int = 0
    use_case: str | None = None
    team_size: str | None = None
    unlimited: bool = False  # on the allow list: runs on our keys with no limit


def _info(u: User) -> UserInfo:
    return UserInfo(
        id=u.id,
        email=u.email,
        name=u.name,
        accepted_current_terms=u.terms_version == config.LEGAL_VERSION,
        onboarded=u.onboarded_at is not None,
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
    """Give one free run back. Only runner._fail calls this: once per job, after a service problem."""
    with session() as s:
        s.execute(update(User).where(User.id == user_id, User.free_runs_used > 0).values(free_runs_used=User.free_runs_used - 1))


def delete_user(user_id: int) -> None:
    """Hard delete: the account, its usage rows and any in-progress job. Nothing else about the user is stored."""
    with session() as s:
        s.execute(delete(ResearchJob).where(ResearchJob.user_id == user_id))
        s.execute(delete(UsageDaily).where(UsageDaily.user_id == user_id))  # portable, no FK reliance
        s.execute(delete(User).where(User.id == user_id))

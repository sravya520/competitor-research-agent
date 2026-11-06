from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from backend import config
from backend.db import session
from backend.models import UsageDaily


@dataclass(frozen=True)
class Quota:
    ok: bool
    reason: str | None  # None | "user" | "global"
    remaining: int      # this user's runs left today, after this call


def _today() -> date:
    return datetime.now(timezone.utc).date()  # limits reset at 00:00 UTC


def _left(s, user_id: int, day: date) -> int:
    used = s.scalar(select(UsageDaily.runs).where(UsageDaily.user_id == user_id, UsageDaily.day == day)) or 0
    return max(config.DAILY_RUNS_PER_USER - used, 0)


def remaining(user_id: int, day: date | None = None) -> int:
    with session() as s:
        return _left(s, user_id, day or _today())


def try_consume(user_id: int, day: date | None = None) -> Quota:
    """Reserve one research run. Call BEFORE starting the pipeline. The daily count is never refunded, even
    when a service problem gives the free run back (runner._fail), because a failed run still cost quota."""
    day = day or _today()
    with session() as s:
        # ponytail: the global cap is a read-then-write soft limit and can overshoot by a few under
        # concurrency. Fine at this scale; make it atomic if abuse ever matters.
        total = s.scalar(select(func.coalesce(func.sum(UsageDaily.runs), 0)).where(UsageDaily.day == day))
        if total >= config.DAILY_RUNS_GLOBAL:
            return Quota(False, "global", _left(s, user_id, day))

        # Atomic per-user increment: only succeeds while under the limit.
        bump = (
            update(UsageDaily)
            .where(UsageDaily.user_id == user_id, UsageDaily.day == day, UsageDaily.runs < config.DAILY_RUNS_PER_USER)
            .values(runs=UsageDaily.runs + 1)
        )
        if s.execute(bump).rowcount == 0:
            if s.get(UsageDaily, (user_id, day)) is not None:
                return Quota(False, "user", 0)  # row exists, so the user is at the limit
            try:
                with s.begin_nested():
                    s.add(UsageDaily(user_id=user_id, day=day, runs=1))
                    s.flush()
            except IntegrityError:  # another tab created the row first: retry the bump once
                if s.execute(bump).rowcount == 0:
                    return Quota(False, "user", 0)
        return Quota(True, None, _left(s, user_id, day))

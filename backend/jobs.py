"""Research jobs: the working state of a run, kept in the database so it outlives any one connection.

On Vercel a WebSocket (and so a Streamlit session) lasts under a minute, but a run takes 30-90 s.
The run therefore happens in a background thread (runner.py) that writes its progress and results
here, and the page only reads them. Rows are temporary: see models.ResearchJob.
"""

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, update

from backend.db import session
from backend.models import ResearchJob

STALE_AFTER_S = 90   # a running job with no heartbeat for this long lost its worker
KEEP_FOR = timedelta(hours=24)
KEEP_LAST = 10        # runs listed in the sidebar; older ones are deleted when a new one starts
MAX_LOG_LINES = 200


@dataclass
class Job:
    id: str
    user_id: int
    company_name: str
    company_url: str
    status: str            # running | review | failed
    stage: str
    fail_reason: str | None
    key_mode: str          # house | own
    method: str = "general"
    log: list[str] = field(default_factory=list)
    state: dict = field(default_factory=dict)
    heartbeat_at: datetime | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _job(r: ResearchJob) -> Job:
    return Job(
        r.id, r.user_id, r.company_name, r.company_url or "", r.status, r.stage, r.fail_reason,
        r.key_mode, r.method or "general", json.loads(r.log or "[]"), json.loads(r.state or "{}"), r.heartbeat_at,
    )


def create(user_id: int, company_name: str, company_url: str, key_mode: str, method: str = "general") -> str:
    purge_old()
    job_id = uuid.uuid4().hex
    with session() as s:
        s.add(ResearchJob(id=job_id, user_id=user_id, company_name=company_name[:255],
                          company_url=company_url[:500], key_mode=key_mode, method=method[:32]))
        s.flush()
        old = s.scalars(select(ResearchJob.id).where(ResearchJob.user_id == user_id)
                        .order_by(ResearchJob.created_at.desc()).offset(KEEP_LAST)).all()
        if old:
            s.execute(delete(ResearchJob).where(ResearchJob.id.in_(old)))
    return job_id


def get(job_id: str) -> Job | None:
    with session() as s:
        r = s.get(ResearchJob, job_id)
        return _job(r) if r else None


def get_for_user(user_id: int, job_id: str | None) -> Job | None:
    """The job, only if it belongs to this user (ids come from the URL, so never trust them)."""
    job = get(job_id) if job_id else None
    return job if job and job.user_id == user_id else None


@dataclass
class JobRow:
    id: str
    company_name: str
    status: str


def list_for(user_id: int) -> list[JobRow]:
    """Newest first, light rows for the sidebar."""
    with session() as s:
        rows = s.execute(
            select(ResearchJob.id, ResearchJob.company_name, ResearchJob.status)
            .where(ResearchJob.user_id == user_id).order_by(ResearchJob.created_at.desc()).limit(KEEP_LAST)
        ).all()
        return [JobRow(*r) for r in rows]


def latest_for(user_id: int) -> Job | None:
    with session() as s:
        r = s.scalar(select(ResearchJob).where(ResearchJob.user_id == user_id).order_by(ResearchJob.created_at.desc()))
        return _job(r) if r else None


def log(job_id: str, message: str) -> None:
    with session() as s:
        r = s.get(ResearchJob, job_id)
        if r is None:
            return  # the user started a new search or deleted the account: nothing to write to
        lines = json.loads(r.log or "[]")
        lines.append(str(message)[:300])
        r.log = json.dumps(lines[-MAX_LOG_LINES:])
        r.heartbeat_at = _now()


def merge_state(job_id: str, **parts) -> None:
    with session() as s:
        r = s.get(ResearchJob, job_id)
        if r is None:
            return
        state = json.loads(r.state or "{}")
        state.update(parts)
        r.state = json.dumps(state)
        r.heartbeat_at = _now()


def update_job(job_id: str, **fields) -> None:
    """Set status / stage / fail_reason, and count it as a sign of life."""
    with session() as s:
        s.execute(update(ResearchJob).where(ResearchJob.id == job_id).values(heartbeat_at=_now(), **fields))


def touch(job_id: str) -> None:
    update_job(job_id)


def claim_stale(job_id: str) -> bool:
    """True for exactly one caller when a running job has lost its worker; that caller restarts it."""
    cutoff = _now() - timedelta(seconds=STALE_AFTER_S)
    with session() as s:
        res = s.execute(
            update(ResearchJob)
            .where(ResearchJob.id == job_id, ResearchJob.status == "running", ResearchJob.heartbeat_at < cutoff)
            .values(heartbeat_at=_now())
        )
        return res.rowcount == 1


def created_at(job_id: str) -> datetime | None:
    with session() as s:
        r = s.get(ResearchJob, job_id)
        if r is None or r.created_at is None:
            return None
        return r.created_at if r.created_at.tzinfo else r.created_at.replace(tzinfo=timezone.utc)


def delete_job(job_id: str) -> None:
    with session() as s:
        s.execute(delete(ResearchJob).where(ResearchJob.id == job_id))


def delete_for_user(user_id: int) -> None:
    with session() as s:
        s.execute(delete(ResearchJob).where(ResearchJob.user_id == user_id))


def purge_old() -> None:
    with session() as s:
        s.execute(delete(ResearchJob).where(ResearchJob.created_at < _now() - KEEP_FOR))

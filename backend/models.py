from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Google's stable subject id is the identity; email can change.
    google_sub: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str | None] = mapped_column(String(255))
    # Which Terms/Privacy version the user agreed to, and when (proof of consent).
    terms_version: Mapped[str | None] = mapped_column(String(32))
    terms_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_login_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    # Onboarding answers (why they use the tool, team size) and when they finished or skipped it.
    use_case: Mapped[str | None] = mapped_column(String(120))
    team_size: Mapped[str | None] = mapped_column(String(32))
    onboarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The user's own API keys, encrypted (backend/vault.py). Never stored in the clear.
    gemini_key_enc: Mapped[str | None] = mapped_column(Text)
    tavily_key_enc: Mapped[str | None] = mapped_column(Text)
    # Runs spent on OUR keys, for life. Compared with config.FREE_RUNS.
    free_runs_used: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Teammate emails the user typed in onboarding (JSON list). Saved for when sharing exists; nothing is sent.
    team_invites: Mapped[str | None] = mapped_column(Text)


class ResearchJob(Base):
    """Working state of one research run, so it survives a dropped connection.

    Temporary by design: a user keeps their 10 most recent runs, each deleted when they delete it,
    when they delete the account, or after 24 hours (legal/privacy.md section 2).
    """

    __tablename__ = "research_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    company_name: Mapped[str] = mapped_column(String(255))
    company_url: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(16), default="running")  # running | review | failed
    stage: Mapped[str] = mapped_column(String(16), default="identify")
    fail_reason: Mapped[str | None] = mapped_column(String(32))
    key_mode: Mapped[str] = mapped_column(String(8), default="house")  # house | own
    method: Mapped[str] = mapped_column(String(32), default="general", server_default="general")
    log: Mapped[str] = mapped_column(Text, default="[]")    # JSON list of progress lines
    state: Mapped[str] = mapped_column(Text, default="{}")  # JSON: identity, research, verified, ...
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class UsageDaily(Base):
    """One row per user per UTC day: how many research runs they started."""

    __tablename__ = "usage_daily"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    runs: Mapped[int] = mapped_column(Integer, default=0)

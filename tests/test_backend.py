"""Backend self-check: accounts, usage limits and job records.

Runs with the rest of the suite (python -m unittest discover -s tests) or alone
(python tests/test_backend.py). Skips with the install command if the web packages are missing.
Uses a throwaway SQLite file and tiny limits (tests/web_setup.py); never touches data/cra.db.
"""

import os
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import web_setup  # noqa: E402  (sets the environment; must come before backend)

web_setup.require_web_packages()

from sqlalchemy import func, select  # noqa: E402

from backend import config, jobs, usage, users  # noqa: E402
from backend.db import session  # noqa: E402
from backend.models import ResearchJob, UsageDaily, User  # noqa: E402

DAY = date(2026, 1, 1)



class BackendTests(unittest.TestCase):
    def test_login_is_idempotent_and_normalizes_email(self):
        a = users.upsert_login("sub-a", "  Ada@Example.COM ", "Ada")
        again = users.upsert_login("sub-a", "ada@example.com", "Ada L.")
        assert again.id == a.id and again.email == "ada@example.com" and again.name == "Ada L."
        assert a.accepted_current_terms is False


    def test_login_requires_identity(self):
        for bad in (("", "x@y.z"), ("sub", "")):
            try:
                users.upsert_login(*bad, None)
            except ValueError:
                continue
            raise AssertionError("empty sub/email must be rejected")


    def test_terms_acceptance_is_versioned(self):
        u = users.upsert_login("sub-t", "t@example.com", None)
        users.accept_terms(u.id)
        assert users.upsert_login("sub-t", "t@example.com", None).accepted_current_terms is True
        with session() as s:  # simulate an older accepted version
            s.get(User, u.id).terms_version = "2000-01-01"
        assert users.upsert_login("sub-t", "t@example.com", None).accepted_current_terms is False


    def test_per_user_limit_then_denied_then_next_day_resets(self):
        u = users.upsert_login("sub-q", "q@example.com", None)
        left = [usage.try_consume(u.id, DAY) for _ in range(3)]
        assert [q.ok for q in left] == [True, True, True]
        assert [q.remaining for q in left] == [2, 1, 0]
        denied = usage.try_consume(u.id, DAY)
        assert (denied.ok, denied.reason, denied.remaining) == (False, "user", 0)
        assert usage.remaining(u.id, DAY) == 0
        assert usage.try_consume(u.id, DAY + timedelta(days=1)).ok is True  # new UTC day


    def test_global_cap_blocks_everyone(self):
        day = DAY + timedelta(days=10)
        ids = [users.upsert_login(f"sub-g{i}", f"g{i}@example.com", None).id for i in range(3)]
        ok = 0
        for uid in ids:  # 3 users x up to 3 runs = 9 attempts, cap is 5
            for _ in range(3):
                ok += usage.try_consume(uid, day).ok
        assert ok == config.DAILY_RUNS_GLOBAL == 5
        assert usage.try_consume(ids[0], day).reason in ("global", "user")


    def test_delete_removes_user_and_usage(self):
        u = users.upsert_login("sub-d", "d@example.com", None)
        usage.try_consume(u.id, DAY + timedelta(days=20))
        users.delete_user(u.id)
        with session() as s:
            assert s.get(User, u.id) is None
            assert s.scalar(select(func.count()).select_from(UsageDaily).where(UsageDaily.user_id == u.id)) == 0
        # the same Google account can sign up again, as a fresh user with no consent or usage carried over
        again = users.upsert_login("sub-d", "d@example.com", None)
        assert again.accepted_current_terms is False
        assert usage.remaining(again.id, DAY + timedelta(days=20)) == config.DAILY_RUNS_PER_USER


    def test_free_run_is_spent_once_and_can_be_refunded(self):
        u = users.upsert_login("sub-f", "f@example.com", None)
        assert u.free_runs_left == 1
        assert users.consume_free_run(u.id) is True
        assert users.consume_free_run(u.id) is False  # only one free run per user, for life
        assert users.get_info(u.id).free_runs_left == 0
        users.refund_free_run(u.id)  # a run that died on a service problem is given back
        assert users.consume_free_run(u.id) is True


    def test_own_keys_are_encrypted_at_rest_and_round_trip(self):
        u = users.upsert_login("sub-k", "k@example.com", None)
        assert users.load_keys(u.id) is None and users.get_info(u.id).has_own_keys is False
        users.save_keys(u.id, " AIzaGEMINI1234 ", "tvly-SEARCH5678")
        with session() as s:
            row = s.get(User, u.id)
            assert "AIzaGEMINI1234" not in row.gemini_key_enc and "tvly-SEARCH5678" not in row.tavily_key_enc
        keys = users.load_keys(u.id)
        assert (keys.gemini, keys.tavily) == ("AIzaGEMINI1234", "tvly-SEARCH5678")
        assert users.key_hints(u.id) == ("…1234", "…5678")
        assert users.get_info(u.id).has_own_keys is True
        users.clear_keys(u.id)
        assert users.load_keys(u.id) is None


    def test_keys_unreadable_after_secret_rotation_do_not_crash(self):
        u = users.upsert_login("sub-r", "r@example.com", None)
        users.save_keys(u.id, "g-key", "t-key")
        old = config.KEY_VAULT_SECRET
        try:
            config.KEY_VAULT_SECRET = "a-different-secret"
            assert users.load_keys(u.id) is None
        finally:
            config.KEY_VAULT_SECRET = old


    def test_allow_listed_emails_are_unlimited_everyone_else_is_not(self):
        owner = users.upsert_login("sub-al1", "Smit.UXDesign@Gmail.com", None)
        friend = users.upsert_login("sub-al2", "sravyadangeti520@gmail.com", None)
        other = users.upsert_login("sub-al3", "someone@example.com", None)
        assert owner.unlimited and friend.unlimited and not other.unlimited
        assert users.get_info(owner.id).unlimited is True


    def test_onboarding_steps_and_skip(self):
        u = users.upsert_login("sub-o", "o@example.com", None)
        assert (u.use_case, u.team_size, u.onboarded) == (None, None, False)
        users.save_use_case(u.id, "Planning a product roadmap")
        users.save_team_size(u.id, "2 to 5")
        users.finish_onboarding(u.id)
        done = users.get_info(u.id)
        assert (done.use_case, done.team_size, done.onboarded) == ("Planning a product roadmap", "2 to 5", True)


    def test_job_lifecycle_history_ownership_stale_claim_and_cleanup(self):
        u = users.upsert_login("sub-j", "j@example.com", None)
        other = users.upsert_login("sub-j2", "j2@example.com", None)
        first = jobs.create(u.id, "Notion", "", "house")
        second = jobs.create(u.id, "Coda", "https://coda.io", "own", "general")
        assert [r.company_name for r in jobs.list_for(u.id)] == ["Coda", "Notion"]  # newest first, both kept
        assert jobs.get_for_user(u.id, first).company_name == "Notion"
        assert jobs.get_for_user(other.id, first) is None  # a job id from the URL is useless to anyone else
        assert jobs.get_for_user(u.id, None) is None and jobs.get_for_user(u.id, "nope") is None
        jobs.log(second, "[search] coda")
        jobs.merge_state(second, identity={"x": 1})
        jobs.merge_state(second, sources=["https://a"])
        j = jobs.get(second)
        assert j.log == ["[search] coda"] and j.state == {"identity": {"x": 1}, "sources": ["https://a"]} and j.method == "general"
        assert jobs.claim_stale(second) is False  # fresh heartbeat: nobody may restart it
        with session() as s:  # simulate a worker that died two minutes ago
            s.get(ResearchJob, second).heartbeat_at = jobs._now() - timedelta(minutes=2)
        assert jobs.claim_stale(second) is True and jobs.claim_stale(second) is False  # exactly one caller wins
        jobs.update_job(second, status="review")
        assert jobs.get(second).status == "review"
        with session() as s:  # 24 h retention
            s.get(ResearchJob, second).created_at = jobs._now() - timedelta(hours=25)
        jobs.purge_old()
        assert jobs.get(second) is None and jobs.get(first) is not None


    def test_an_expired_job_is_never_served_even_before_any_cleanup_runs(self):
        u = users.upsert_login("sub-exp", "exp@example.com", None)
        jid = jobs.create(u.id, "Old Co", "", "house")
        with session() as s:
            s.get(ResearchJob, jid).created_at = jobs._now() - timedelta(hours=25)
        assert jobs.latest_for(u.id) is None
        assert jobs.get_for_user(u.id, jid) is None
        with session() as s:
            assert s.get(ResearchJob, jid) is None  # reading it was enough to erase it

    def test_just_under_a_day_old_is_still_served(self):
        u = users.upsert_login("sub-young", "young@example.com", None)
        jid = jobs.create(u.id, "Young Co", "", "house")
        with session() as s:
            s.get(ResearchJob, jid).created_at = jobs._now() - timedelta(hours=23)
        assert jobs.get_for_user(u.id, jid) is not None and jobs.latest_for(u.id).id == jid

    def test_loading_the_rail_cleans_up_everyones_expired_jobs(self):
        u = users.upsert_login("sub-rail", "rail@example.com", None)
        other = users.upsert_login("sub-rail2", "rail2@example.com", None)
        expired = jobs.create(other.id, "Old Co", "", "house")
        with session() as s:
            s.get(ResearchJob, expired).created_at = jobs._now() - timedelta(hours=25)
        assert jobs.list_for(u.id) == []
        with session() as s:
            assert s.get(ResearchJob, expired) is None

    def test_only_one_caller_can_fail_a_job(self):
        u = users.upsert_login("sub-once", "once@example.com", None)
        jid = jobs.create(u.id, "Co", "", "house")
        assert jobs.fail_once(jid, "error") is True and jobs.fail_once(jid, "quota") is False
        assert jobs.get(jid).fail_reason == "error"  # the first reason stands

    def test_a_job_that_reached_review_cannot_be_failed(self):
        u = users.upsert_login("sub-rev", "rev@example.com", None)
        jid = jobs.create(u.id, "Co", "", "house")
        jobs.update_job(jid, status="review")
        assert jobs.fail_once(jid, "error") is False and jobs.get(jid).status == "review"

    def test_only_the_ten_newest_jobs_are_kept(self):
        u = users.upsert_login("sub-cap", "cap@example.com", None)
        ids = [jobs.create(u.id, f"Co{i}", "", "house") for i in range(12)]
        kept = [r.id for r in jobs.list_for(u.id)]
        assert len(kept) == jobs.KEEP_LAST == 10 and ids[-1] in kept and ids[0] not in kept and ids[1] not in kept


    def _database_with_teammate_emails(self, name):
        from sqlalchemy import create_engine, text
        url = f"sqlite:///{Path(web_setup.TMP, name).as_posix()}"
        eng = create_engine(url)
        with eng.begin() as c:
            c.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, google_sub VARCHAR(255), email VARCHAR(320), "
                           "team_size VARCHAR(32), team_invites TEXT)"))
            c.execute(text("INSERT INTO users (id, google_sub, email, team_size, team_invites) "
                           "VALUES (1, 's', 'e@x.y', '2 to 5', '[\"ada@example.com\"]')"))
        return url, eng

    def test_saved_teammate_emails_are_erased_and_the_rest_of_the_user_is_kept(self):
        from sqlalchemy import inspect, text

        from backend.db import _drop_retired_columns

        _, eng = self._database_with_teammate_emails("invites.db")
        _drop_retired_columns(eng)
        assert "team_invites" not in {c["name"] for c in inspect(eng).get_columns("users")}
        with eng.connect() as c:
            assert c.execute(text("SELECT email, team_size FROM users WHERE id = 1")).one() == ("e@x.y", "2 to 5")
        _drop_retired_columns(eng)  # every later start runs it again and must not fail

    def test_connecting_to_an_old_database_is_what_erases_them(self):
        from sqlalchemy import inspect

        from backend import db

        url, _ = self._database_with_teammate_emails("invites-start.db")
        with patch.object(db, "_engine", None), patch.object(config, "DATABASE_URL", url):
            engine = db.get_engine()
            assert "team_invites" not in {c["name"] for c in inspect(engine).get_columns("users")}

    def test_postgres_drop_tolerates_two_instances_starting_at_once(self):
        from backend.db import RETIRED_COLUMNS, _drop_retired_columns

        conn = MagicMock()
        engine = MagicMock()
        engine.dialect.name = "postgresql"
        engine.begin.return_value.__enter__.return_value = conn
        inspector = MagicMock()
        inspector.get_columns.return_value = [{"name": RETIRED_COLUMNS[0][1]}]
        with patch("backend.db.inspect", return_value=inspector):
            _drop_retired_columns(engine)
        assert str(conn.execute.call_args[0][0]) == "ALTER TABLE users DROP COLUMN IF EXISTS team_invites"

    def test_delete_user_removes_their_job(self):
        u = users.upsert_login("sub-dj", "dj@example.com", None)
        jid = jobs.create(u.id, "Airtable", "", "house")
        users.delete_user(u.id)
        assert jobs.get(jid) is None


    def test_new_columns_are_added_to_an_existing_database(self):
        from sqlalchemy import create_engine, inspect, text

        from backend.db import _add_missing_columns

        eng = create_engine(f"sqlite:///{Path(web_setup.TMP, 'old.db').as_posix()}")
        with eng.begin() as c:  # the schema as it was before onboarding existed
            c.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, google_sub VARCHAR(255), email VARCHAR(320), name VARCHAR(255), "
                           "terms_version VARCHAR(32), terms_accepted_at DATETIME, created_at DATETIME, last_login_at DATETIME)"))
            c.execute(text("INSERT INTO users (id, google_sub, email) VALUES (1, 's', 'e@x.y')"))
            c.execute(text("CREATE TABLE usage_daily (user_id INTEGER, day DATE, runs INTEGER, PRIMARY KEY (user_id, day))"))
            c.execute(text("CREATE TABLE research_jobs (id VARCHAR(32) PRIMARY KEY, user_id INTEGER, company_name VARCHAR(255), company_url VARCHAR(500), "
                           "status VARCHAR(16), stage VARCHAR(16), fail_reason VARCHAR(32), key_mode VARCHAR(8), log TEXT, state TEXT, "
                           "heartbeat_at DATETIME, created_at DATETIME)"))
        _add_missing_columns(eng)
        cols = {c["name"] for c in inspect(eng).get_columns("users")}
        assert {"use_case", "team_size", "onboarded_at", "gemini_key_enc", "tavily_key_enc", "free_runs_used"} <= cols
        with eng.connect() as c:
            assert c.execute(text("SELECT free_runs_used FROM users WHERE id = 1")).scalar() == 0  # old rows start at 0
            c.execute(text("INSERT INTO research_jobs (id, user_id) VALUES ('old', 1)"))
            assert c.execute(text("SELECT method FROM research_jobs WHERE id = 'old'")).scalar() == "general"  # quoted text default


    def test_postgres_url_gets_driver_prefix(self):
        import importlib

        os.environ["DATABASE_URL"] = "postgres://u:p@host/db"
        try:
            assert importlib.reload(config).DATABASE_URL == "postgresql+psycopg://u:p@host/db"
        finally:
            os.environ["DATABASE_URL"] = web_setup.DATABASE_URL
            importlib.reload(config)


if __name__ == "__main__":
    unittest.main()

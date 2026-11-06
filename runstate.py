"""One research run's own state, owned by that run and nothing else.

Everything here used to live at module level in tools.py and pipeline.py.
That works for a CLI, which does one run per process, and breaks on the
deployed app: Streamlit gives each browser session its own ScriptRunner
THREAD inside ONE process, so a module-level ledger is shared by every
visitor at once. One visitor submitting cleared another's evidence mid-run,
and because evaluate.drop_fabricated_sources treats the ledger as proof a
URL was really fetched, the second visitor's genuine citations were then
stripped from their report as fabricated. The anti-hallucination check was
deleting true evidence.

A RunState is created once per run and passed explicitly: the CLI makes one
per invocation, the web app one per research and keeps it in
st.session_state (the report is written in a later rerun and needs this
ledger), the eval harness one per case, the benchmark harness one per
benchmark case. There is no module-level fallback to inherit by accident.

contextvars would also carry this, and is not used: tools.make_tools()
closes over the run, so the state travels with the function rather than
with the thread. That holds even if the SDK invokes a tool from a worker
thread, which a context variable set on the calling thread would not.

Standard library only, so it can be imported from anywhere here, including
tests with no API keys.
"""

import threading

# Benchmark fairness control, OFF by default.
#
# No character limit exists in production: Tavily snippets arrive at whatever
# length Tavily sends (observed median 1,144, max 1,438) and extract returns
# full pages uncapped. Enabling this in normal use would therefore change
# behaviour, so it stays off unless a benchmark turns it on.
#
# It exists because providers return very different volumes of text, and
# without a shared cap the comparison would partly measure verbosity rather
# than retrieval quality.
DEFAULT_TRUNCATION = {
    "enabled": False,
    "search_chars": 1500,   # just above the observed Tavily search maximum
    "page_chars": 25000,
}


def _silent(_message) -> None:
    """Progress sink for a run nobody is watching."""


class RunState:
    """The source ledger, progress sink, counters and provider for one run.

    Thread-safe in its own right. A single run is normally driven by one
    thread, but the model's tool calls may arrive from another, and two runs
    sharing one process must never be able to interleave into a half-updated
    counter.
    """

    def __init__(self, progress=print, provider=None, provider_name=None,
                 truncation=None):
        self._lock = threading.Lock()
        self._sources: set[str] = set()
        self._model_versions: set[str] = set()

        # Where [search] and [extract] lines go. The CLI wants print; the web
        # app points this at its own st.status.write, which is exactly what
        # used to leak between visitors when one process held one hook.
        self.progress = progress or _silent

        # The provider belongs to the run, because the benchmark harness
        # switches it per case. Its underlying clients do not: those stay
        # process-wide, in tools.provider_for().
        self.provider = provider
        self.provider_name = provider_name

        self.truncation = dict(DEFAULT_TRUNCATION if truncation is None
                               else truncation)
        self._truncation_counts = {
            "search_results": 0, "search_truncated": 0,
            "pages": 0, "pages_truncated": 0,
        }

    # --- the source ledger ------------------------------------------------

    def record_source(self, url: str) -> None:
        """Note that this run really did fetch a URL.

        Called only for a successful fetch. That single rule is what keeps
        evaluate.check_sources_are_real meaningful: the ledger is treated
        downstream as proof, so recording a failure would let a model cite a
        page nobody ever read and pass the fabrication check.
        """
        with self._lock:
            self._sources.add(url)

    def sources_consulted(self) -> list[str]:
        """Every URL this run actually fetched, sorted."""
        with self._lock:
            return sorted(self._sources)

    # --- model provenance -------------------------------------------------

    def note_model_version(self, version: str) -> None:
        """Record which model version answered, when the response says.

        MODEL is an alias ending in "-latest", so it is a pointer that
        moves. A stored run is only comparable with a later one if the
        version that produced it is known.
        """
        if version:
            with self._lock:
                self._model_versions.add(version)

    def model_versions(self) -> list[str]:
        """Resolved model versions seen during this run, sorted."""
        with self._lock:
            return sorted(self._model_versions)

    # --- the benchmark cap ------------------------------------------------

    def cap(self, text: str, limit_key: str, total_key: str,
            truncated_key: str) -> str:
        """Apply the shared per-result cap and record whether it bit."""
        with self._lock:
            self._truncation_counts[total_key] += 1
            enabled = self.truncation["enabled"]
            limit = self.truncation[limit_key]
            if enabled and len(text) > limit:
                self._truncation_counts[truncated_key] += 1
                return text[:limit]
        return text

    def truncation_settings(self) -> dict:
        """The active settings, recorded into benchmark result metadata."""
        return dict(self.truncation)

    def truncation_stats(self) -> dict:
        """Counts plus the share truncated, per operation."""
        with self._lock:
            stats = dict(self._truncation_counts)

        stats["search_truncated_share"] = (
            stats["search_truncated"] / stats["search_results"]
            if stats["search_results"] else None
        )
        stats["pages_truncated_share"] = (
            stats["pages_truncated"] / stats["pages"] if stats["pages"] else None
        )
        return stats

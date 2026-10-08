# Archived results

`raw_retrieval_INVALID_whitespace_bug.jsonl`: the first Experiment A pass.
Its recall figures (tavily 79%, firecrawl 91%) are **wrong and must not be
quoted**. Fact matching compared raw substrings, so a page that broke a phrase
across lines scored as a miss. This penalised providers for line-breaking
style rather than for content: Firecrawl scored 0/1 on dataleap.ai for a
tagline its content did contain.

Kept only to show the correction happened. Latency, content_chars and
boilerplate_share in this file were unaffected by the bug.

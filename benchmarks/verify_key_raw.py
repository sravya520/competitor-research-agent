"""Check an answer-key fact against the official page's raw HTML.

Independent of both benchmarked providers: a plain HTTP GET, no extraction
service. Used to settle facts that every arm missed, where the question is
whether the key's wording is a paraphrase or the text genuinely is not in the
server-rendered HTML.

    python -m benchmarks.verify_key_raw https://brickanta.com "Agentic AI for Construction"

Reports whether each phrase appears in the raw bytes and in a tag-stripped
rendering, because server-rendered text is often split across tags.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys

import httpx

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")


def fetch(url: str) -> str:
    response = httpx.get(url, headers={"User-Agent": UA}, follow_redirects=True,
                         timeout=30.0)
    response.raise_for_status()
    return response.text


def strip_tags(raw: str) -> str:
    without_script = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", raw,
                            flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", without_script)
    return re.sub(r"\s+", " ", html.unescape(text))


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).lower()


def check(url: str, phrases: list[str]) -> dict:
    raw = fetch(url)
    text = strip_tags(raw)
    result = {"url": url, "raw_bytes": len(raw), "stripped_chars": len(text),
              "phrases": {}}
    for phrase in phrases:
        needle = norm(phrase)
        in_text = needle in norm(text)
        index = norm(text).find(needle)
        result["phrases"][phrase] = {
            "in_raw_html": needle in norm(raw),
            "in_rendered_text": in_text,
            "context": text[max(0, index - 80):index + 120] if in_text else None,
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("phrases", nargs="+")
    args = parser.parse_args()
    out = check(args.url, args.phrases)
    print(json.dumps(out, indent=1, ensure_ascii=True))


if __name__ == "__main__":
    main()

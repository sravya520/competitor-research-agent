"""The three LLM steps: identify the company, research it, verify the result.

Each step is a plain function that takes data in and returns a validated
Pydantic object, so main.py can read as a sequence of steps rather than a
tangle of API calls.
"""

from google.genai import types
from tenacity import retry

import prompts
from config import MODEL, RETRY_SETTINGS, SYSTEM_INSTRUCTION, gemini_client
from schemas import CompanyIdentity, Competitor, CompetitorResearch, CompetitorVerification
from tools import extract_company_page, search_web


def _agent_config(response_schema, tools: list, max_tool_calls: int, use_system_prompt: bool = True):
    """Config for a tool-using call that must return a validated object.

    max_tool_calls must be at least 2 for tool use to work at all: one unit
    lets the model request a tool, the next lets it read the result and
    answer. A budget of 1 leaves the loop unfinished and .parsed comes back
    as None.
    """
    return types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION if use_system_prompt else None,
        tools=tools,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(
            maximum_remote_calls=max_tool_calls,
        ),
        response_mime_type="application/json",
        response_schema=response_schema,
    )


@retry(**RETRY_SETTINGS)
def _send(chat, prompt: str):
    return chat.send_message(prompt)


@retry(**RETRY_SETTINGS)
def _generate(prompt: str, config):
    return gemini_client.models.generate_content(
        model=MODEL, contents=prompt, config=config,
    )


def identify_company(company_name: str, company_url: str) -> CompanyIdentity | None:
    """Establish which company we are actually researching.

    When a URL is given, its page content anchors the identity and outranks
    search results. Returns None if the model never produced a valid answer.
    """
    anchor_content = extract_company_page(company_url) if company_url else ""

    chat = gemini_client.chats.create(
        model=MODEL,
        config=_agent_config(
            CompanyIdentity, tools=[search_web], max_tool_calls=3, use_system_prompt=False,
        ),
    )
    response = _send(chat, prompts.identity_prompt(company_name, company_url, anchor_content))
    return response.parsed


def research_competitors(company_name: str, identity: CompanyIdentity) -> CompetitorResearch | None:
    """Find competitors, letting the model choose its own searches.

    Given both search_web and extract_company_page: search alone tends to
    surface "best agencies" roundup content (that's what ranks for those
    queries), so once a listicle names a candidate, the model can extract
    that company's own site to verify the claim rather than trust the
    roundup's numbers — the same anchoring pattern that fixed identity,
    applied to competitors.
    """
    chat = gemini_client.chats.create(
        model=MODEL,
        config=_agent_config(
            CompetitorResearch,
            tools=[search_web, extract_company_page],
            max_tool_calls=8,
        ),
    )
    response = _send(chat, prompts.research_prompt(company_name, identity))
    return response.parsed


def verify_competitors(
    company_name: str,
    identity: CompanyIdentity,
    competitors: list[Competitor],
) -> list[CompetitorVerification]:
    """Second opinion on the proposed competitors.

    Deliberately a fresh call with no shared history: a model asked to
    re-check its own reasoning tends to agree with itself.
    """
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=list[CompetitorVerification],
    )
    response = _generate(prompts.verification_prompt(company_name, identity, competitors), config)
    return response.parsed or []


def apply_verifications(
    competitors: list[Competitor],
    verifications: list[CompetitorVerification],
) -> tuple[list[Competitor], list[tuple[str, str]]]:
    """Split competitors into (kept, [(name, rejection_reason), ...]).

    Pairs by index, not by name — model-generated names drift between calls.
    A competitor with no matching verdict is dropped rather than kept: an
    unchecked claim should not reach the report by default.
    """
    kept: list[Competitor] = []
    excluded: list[tuple[str, str]] = []

    for i, competitor in enumerate(competitors):
        verdict = next((v for v in verifications if v.index == i), None)
        if verdict and verdict.verified:
            kept.append(competitor)
        else:
            reason = verdict.reason if verdict else "No verification returned for this competitor."
            excluded.append((competitor.name, reason))

    return kept, excluded

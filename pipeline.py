"""The three LLM steps: identify the company, research it, verify the result.

Each step is a plain function that takes data in and returns a validated
Pydantic object, so main.py can read as a sequence of steps rather than a
tangle of API calls.
"""

from google.genai import types
from tenacity import retry

import prompts
from config import MODEL, RETRY_SETTINGS, SYSTEM_INSTRUCTION, gemini_client
import tools
from schemas import CompanyIdentity, Competitor, CompetitorResearch, CompetitorVerification


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


def _note_model_version(run, response):
    """Record which model actually answered, then pass the response along.

    MODEL is an alias ending in "-latest", which moves to a new model
    without warning: it resolved to gemini-3.5-flash-lite the last time an
    error named it. A run recorded without this is not comparable with a
    later one, because a changed competitor set would look like a changed
    market when the model changed underneath it.
    """
    run.note_model_version(getattr(response, "model_version", None))
    return response


@retry(**RETRY_SETTINGS)
def _send(chat, prompt: str, run):
    return _note_model_version(run, chat.send_message(prompt))


@retry(**RETRY_SETTINGS)
def _generate(prompt: str, config, run):
    return _note_model_version(run, gemini_client.models.generate_content(
        model=MODEL, contents=prompt, config=config,
    ))


def identify_company(company_name: str, company_url: str, run) -> CompanyIdentity | None:
    """Establish which company we are actually researching.

    When a URL is given, its page content anchors the identity and outranks
    search results. Returns None if the model never produced a valid answer.

    `run` is required, with no default: every URL fetched here belongs in
    that run's ledger, and a step that could silently fall back to shared
    state is how one visitor's evidence ended up in another's report.
    """
    search_web, extract_company_page = tools.make_tools(run)
    anchor_content = extract_company_page(company_url) if company_url else ""

    chat = gemini_client.chats.create(
        model=MODEL,
        config=_agent_config(
            CompanyIdentity, tools=[search_web], max_tool_calls=3, use_system_prompt=False,
        ),
    )
    response = _send(
        chat, prompts.identity_prompt(company_name, company_url, anchor_content), run)
    return response.parsed


def research_competitors(company_name: str, identity: CompanyIdentity,
                         run) -> CompetitorResearch | None:
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
            tools=tools.make_tools(run),
            # Prompt hard-caps the model at 7 tool calls; budget needs to be
            # at least one more than that (the final answer costs a unit
            # too — see _agent_config's docstring), plus a little slack for
            # imperfect compliance rather than cutting it exactly at the edge.
            max_tool_calls=9,
        ),
    )
    response = _send(chat, prompts.research_prompt(company_name, identity), run)
    return response.parsed


def verify_competitors(
    company_name: str,
    identity: CompanyIdentity,
    competitors: list[Competitor],
    run,
) -> list[CompetitorVerification]:
    """Second opinion on the proposed competitors.

    Deliberately a fresh call with no shared history: a model asked to
    re-check its own reasoning tends to agree with itself.
    """
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=list[CompetitorVerification],
    )
    response = _generate(
        prompts.verification_prompt(company_name, identity, competitors), config, run)
    return response.parsed or []


def rejected_competitors(
    competitors: list[Competitor],
    verifications: list[CompetitorVerification],
) -> list[tuple[Competitor, str]]:
    """The competitors verification refused, each with its reason.

    Pairs by index, not by name — model-generated names drift between calls.
    A competitor with no matching verdict is refused rather than kept: an
    unchecked claim should not reach the report by default.

    Returns the objects, not just their names, because a run where every
    candidate is refused still writes a report that shows what was
    considered, and that needs each candidate's sources.
    """
    rejected: list[tuple[Competitor, str]] = []

    for i, competitor in enumerate(competitors):
        verdict = next((v for v in verifications if v.index == i), None)
        if not (verdict and verdict.verified):
            reason = (verdict.reason if verdict
                      else "No verification returned for this competitor.")
            rejected.append((competitor, reason))

    return rejected


def apply_verifications(
    competitors: list[Competitor],
    verifications: list[CompetitorVerification],
) -> tuple[list[Competitor], list[tuple[str, str]]]:
    """Split competitors into (kept, [(name, rejection_reason), ...]).

    The pairing rule lives in rejected_competitors, so the two views of the
    same decision cannot disagree.
    """
    rejected = rejected_competitors(competitors, verifications)
    refused = {id(competitor) for competitor, _ in rejected}

    kept = [competitor for competitor in competitors
            if id(competitor) not in refused]
    excluded = [(competitor.name, reason) for competitor, reason in rejected]

    return kept, excluded

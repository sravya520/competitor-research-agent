from pydantic import BaseModel
from typing import Optional

class CompanyIdentity(BaseModel):
    description: str
    location: Optional[str] = None
    website: Optional[str] = None
    confident_match: bool
    ambiguity_note: Optional[str] = None
    # Verification compares a candidate's scale against the target's.
    # With no scale recorded here it was left guessing, and its verdicts
    # on identical input flipped between runs.
    scale_and_stage: Optional[str] = None

class Competitor(BaseModel):
    name: str
    why_relevant: str
    product_or_service: str
    target_customers: str
    positioning: str
    # Both sides of that comparison are needed. Without this, a real peer
    # whose size is merely unrecorded reads as unverifiable and is cut.
    scale_and_stage: Optional[str] = None
    pricing: Optional[str] = None
    strengths: list[str]
    weaknesses: list[str]
    differentiators: list[str]

    sources: list[str]

class CompetitorResearch(BaseModel):
    company_name: str
    competitors: list[Competitor]
    market_trends: list[str]
    market_gaps_opportunities: list[str]
    potential_threats: list[str]

class CompetitorVerification(BaseModel):
    index: int
    name: str
    verified: bool
    reason: str
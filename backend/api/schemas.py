from pydantic import BaseModel


class ClaimVerdictOut(BaseModel):
    claim_text: str
    verdict: str
    confidence: float
    reasoning: str


class CheckResponse(BaseModel):
    summary: str
    claims_checked: int
    supported_count: int
    refuted_count: int
    unverifiable_count: int
    claim_verdicts: list[ClaimVerdictOut]
    from_cache: bool

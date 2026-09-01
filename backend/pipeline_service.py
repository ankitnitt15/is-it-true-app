import concurrent.futures
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "pipeline"))

from extraction.claim_extractor import extract_claims
from reporting.report_synthesizer import synthesize_report
from shared.models import Claim, ClaimVerdict, Report, VerificationResult
from verification.verifier import verify_claim
from verification.vote_aggregator import aggregate

K_SAMPLES = 1
BATCH_SIZE = 5
NO_CLAIMS_SUMMARY = "No factual claims found in this text -- there's nothing to fact-check here."


def run_fact_check_stream(
    article_text: str,
    article_id: str,
    image_bytes: bytes | None = None,
    image_mime_type: str | None = None,
):
    """Generator yielding progress events as the pipeline runs -- the same
    extract -> verify -> aggregate -> synthesize pipeline as
    systems/FactCheckerAgent/pipeline.py, restructured so api/routes.py can
    stream it live (SSE) instead of only returning a single blocking
    response. Always ends with a "done" event; run_fact_check() below
    drains this for callers that just want the final result.

    Events:
        {"event": "claims_found", "claims": [{"claim_id", "text"}, ...]}
        {"event": "claim_verified", "claim_id", "claim_text", "verdict",
         "confidence", "reasoning"}                    (one per claim)
        {"event": "synthesizing"}
        {"event": "done", "summary", "claims_checked", "supported_count",
         "refuted_count", "unverifiable_count", "claim_verdicts",
         "image_verification_calls"}
    """
    claims = extract_claims(article_text, image_bytes, image_mime_type)

    if not claims:
        # Small talk, greetings, pure opinion, gibberish -- nothing to verify.
        # Skip verification/synthesis entirely: cheaper (1 Gemini call instead
        # of up to N+2) and gives a consistent, friendly message instead of
        # an LLM-phrased "no claims were found" paragraph.
        yield {
            "event": "done",
            "summary": NO_CLAIMS_SUMMARY,
            "claims_checked": 0,
            "supported_count": 0,
            "refuted_count": 0,
            "unverifiable_count": 0,
            "claim_verdicts": [],
            "image_verification_calls": 0,
        }
        return

    yield {
        "event": "claims_found",
        "claims": [{"claim_id": c.claim_id, "text": c.text} for c in claims],
    }

    verdicts_by_id: dict[str, ClaimVerdict] = {}
    results_by_claim: dict[str, list[VerificationResult | None]] = {c.claim_id: [] for c in claims}
    image_verification_calls = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=BATCH_SIZE) as executor:
        future_to_task = {}
        for claim in claims:
            # Most claims are general facts merely printed as text (in the
            # article or in an image) -- only claims about the image's own
            # visual content (claim.needs_image) actually need it looked at
            # again here. Re-attaching it to every verification call was the
            # main latency cost for image checks.
            use_image = image_bytes is not None and claim.needs_image
            if use_image:
                image_verification_calls += 1
            for i in range(K_SAMPLES):
                future = executor.submit(
                    verify_claim,
                    claim,
                    i,
                    image_bytes if use_image else None,
                    image_mime_type if use_image else None,
                )
                future_to_task[future] = (claim, i)

        for future in concurrent.futures.as_completed(future_to_task):
            claim, sample_index = future_to_task[future]
            try:
                result = future.result()
            except Exception as e:
                print(f"sample {sample_index} for claim {claim.claim_id} failed: {e}")
                result = None
            results_by_claim[claim.claim_id].append(result)

            if len(results_by_claim[claim.claim_id]) == K_SAMPLES:
                verdict = aggregate(claim, results_by_claim[claim.claim_id])
                verdicts_by_id[claim.claim_id] = verdict
                yield {
                    "event": "claim_verified",
                    "claim_id": claim.claim_id,
                    "claim_text": claim.text,
                    "verdict": verdict.final_verdict,
                    "confidence": verdict.confidence,
                    "reasoning": verdict.reasoning,
                }

    yield {"event": "synthesizing"}

    # verdicts_by_id fills in whatever order claims finished verifying in --
    # put the final list back in extraction order for the cached report.
    claim_verdicts = [verdicts_by_id[c.claim_id] for c in claims]

    summary = synthesize_report(article_text, claim_verdicts)

    yield {
        "event": "done",
        "summary": summary,
        "claims_checked": len(claims),
        "supported_count": sum(1 for cv in claim_verdicts if cv.final_verdict == "SUPPORTED"),
        "refuted_count": sum(1 for cv in claim_verdicts if cv.final_verdict == "REFUTED"),
        "unverifiable_count": sum(1 for cv in claim_verdicts if cv.final_verdict == "UNVERIFIABLE"),
        "claim_verdicts": [cv.model_dump() for cv in claim_verdicts],
        "image_verification_calls": image_verification_calls,
    }


def run_fact_check(
    article_text: str,
    article_id: str,
    image_bytes: bytes | None = None,
    image_mime_type: str | None = None,
) -> tuple[Report, int]:
    """Drains run_fact_check_stream() for callers that just want the final
    result (api/routes.py's plain JSON /api/check). Returns (Report,
    image_verification_calls) -- the latter feeds the global cost-cap
    accounting in routes.py.
    """
    done_event = None
    for event in run_fact_check_stream(article_text, article_id, image_bytes, image_mime_type):
        if event["event"] == "done":
            done_event = event

    report = Report(
        article_id=article_id,
        claims_checked=done_event["claims_checked"],
        supported_count=done_event["supported_count"],
        refuted_count=done_event["refuted_count"],
        unverifiable_count=done_event["unverifiable_count"],
        claim_verdicts=done_event["claim_verdicts"],
        summary=done_event["summary"],
    )
    return report, done_event["image_verification_calls"]

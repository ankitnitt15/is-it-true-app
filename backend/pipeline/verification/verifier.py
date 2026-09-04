import datetime

from google.genai import types

from common.gemini_client import generate_content
from shared.models import Claim, VerificationResult
from shared.retry import call_with_backoff
from verification.prompts import build_verification_prompt

VERIFICATION_TEMPERATURE = 0.7
CONFIDENCE_FLOOR = 0.4

def verify_claim(
        claim: Claim,
        sample_index: int,
        image_bytes: bytes | None = None,
        image_mime_type: str | None = None,
) -> VerificationResult:
    # The model has no built-in sense of "now" -- without telling it today's
    # date, it has no way to reason about whether a scheduled/anticipated
    # event has already happened, and will confidently (and wrongly) claim
    # real events "haven't happened yet" if they're near/after its training
    # cutoff. See verification/prompts.py for the full reasoning.
    today = datetime.date.today().isoformat()
    prompt = build_verification_prompt(claim.text, today)
    contents = [prompt]
    if image_bytes is not None:
        # Re-attach the same image the claim was extracted from -- without
        # this, a claim about what the image shows gets "verified" against
        # text alone, and the model correctly (if confusingly) says it can't
        # see an image, because in this call it genuinely wasn't given one.
        contents.append(types.Part.from_bytes(data=image_bytes, mime_type=image_mime_type))

    response = call_with_backoff(
        generate_content,
        contents=contents,
        config={
            "response_mime_type": "application/json",
            "response_schema": VerificationResult,
            "temperature": VERIFICATION_TEMPERATURE,
        }
    )
    result = response.parsed
    result.claim_id = claim.claim_id  # the model is never told the real claim_id, so it fabricates one -- overwrite it
    if result.confidence < CONFIDENCE_FLOOR:
        result.verdict = "UNVERIFIABLE"

    return result


if __name__ == "__main__":
    true_claim = Claim(
        claim_id="t1",
        text="The Eiffel Tower is located in Paris, France.",
        span_start=0,
        span_end=0,
    )
    false_claim = Claim(
        claim_id="f1",
        text="The Eiffel Tower is located in London, England.",
        span_start=0,
        span_end=0,
    )

    # kept small (2 calls, not 3) to limit API spend during manual testing
    for claim in (true_claim, false_claim):
        print(f"--- claim: {claim.text} ---")
        for i in range(2):
            result = verify_claim(claim, i)
            print(f"sample {i}: {result.model_dump_json()}")
        print()
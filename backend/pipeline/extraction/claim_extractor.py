import uuid
from pathlib import Path

from google.genai import types

from common.gemini_client import generate_content
from extraction.prompts import build_extraction_prompt
from shared.models import Claim
from shared.retry import call_with_backoff


def extract_claims(
    article_text: str = "",
    image_bytes: bytes | None = None,
    image_mime_type: str | None = None,
) -> list[Claim]:
    prompt = build_extraction_prompt(article_text)
    contents = [prompt]
    if image_bytes is not None:
        contents.append(types.Part.from_bytes(data=image_bytes, mime_type=image_mime_type))

    response = call_with_backoff(
        generate_content,
        contents=contents,
        config={
            "response_mime_type": "application/json",
            "response_schema": list[Claim],
        },
    )
    claims = response.parsed

    # The model invents its own claim_id per claim, with nothing enforcing
    # uniqueness -- if two claims in one response happen to share an id,
    # their verification results silently merge under the same bookkeeping
    # key downstream (pipeline_service.run_verification_batch), which looks
    # like a tied vote between unrelated claims and forces a bogus
    # UNVERIFIABLE. Overwrite with a guaranteed-unique id right away.
    for claim in claims:
        claim.claim_id = str(uuid.uuid4())

    return claims


if __name__ == "__main__":
    article_text = (Path(__file__).parent / "sample_article.txt").read_text(encoding="utf-8")
    claims = extract_claims(article_text)

    for claim in claims:
        print(claim.model_dump_json(indent=2))
        print(f"  span text: {article_text[claim.span_start:claim.span_end]!r}")
        print()

    print(f"Extracted {len(claims)} claims.")

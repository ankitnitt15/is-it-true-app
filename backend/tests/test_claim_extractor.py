from unittest.mock import MagicMock, patch

from extraction.claim_extractor import extract_claims
from shared.models import Claim


def test_duplicate_claim_ids_from_the_model_are_made_unique():
    # Regression test: the model invents its own claim_id per claim with
    # nothing enforcing uniqueness. If two claims share an id, their
    # verification results silently merge downstream (pipeline_service),
    # which looks like a tied vote between unrelated claims and forces a
    # bogus UNVERIFIABLE -- extract_claims must overwrite with fresh,
    # guaranteed-unique ids regardless of what the model returned.
    fake_response = MagicMock()
    fake_response.parsed = [
        Claim(claim_id="dup", text="claim A", span_start=0, span_end=7),
        Claim(claim_id="dup", text="claim B", span_start=8, span_end=15),
    ]

    with patch("extraction.claim_extractor.generate_content", return_value=fake_response):
        claims = extract_claims("claim A. claim B.")

    assert len(claims) == 2
    assert claims[0].claim_id != claims[1].claim_id


def test_extract_claims_passes_image_as_a_content_part():
    fake_response = MagicMock()
    fake_response.parsed = []

    with patch("extraction.claim_extractor.generate_content", return_value=fake_response) as mock_generate:
        extract_claims("some text", image_bytes=b"fake-bytes", image_mime_type="image/png")

    _, kwargs = mock_generate.call_args
    contents = kwargs["contents"]
    assert len(contents) == 2  # prompt text + the image part

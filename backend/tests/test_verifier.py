from unittest.mock import MagicMock, patch

from shared.models import Claim, VerificationResult
from verification.verifier import CONFIDENCE_FLOOR, verify_claim

CLAIM = Claim(claim_id="real-id", text="a claim", span_start=0, span_end=0)


def _fake_response(claim_id, confidence, verdict):
    response = MagicMock()
    response.parsed = VerificationResult(claim_id=claim_id, reasoning="because", confidence=confidence, verdict=verdict)
    return response


def test_low_confidence_is_clamped_to_unverifiable():
    fake_response = _fake_response("model-invented-id", confidence=CONFIDENCE_FLOOR - 0.1, verdict="SUPPORTED")

    with patch("verification.verifier.generate_content", return_value=fake_response):
        result = verify_claim(CLAIM, sample_index=0)

    assert result.verdict == "UNVERIFIABLE"


def test_confident_verdict_passes_through_unchanged():
    fake_response = _fake_response("model-invented-id", confidence=CONFIDENCE_FLOOR + 0.1, verdict="REFUTED")

    with patch("verification.verifier.generate_content", return_value=fake_response):
        result = verify_claim(CLAIM, sample_index=0)

    assert result.verdict == "REFUTED"


def test_claim_id_is_overwritten_with_the_real_one():
    # The model is never told the real claim_id (only the claim text), so it
    # fabricates one -- verify_claim must overwrite it with the real id,
    # otherwise pipeline_service's per-claim bookkeeping breaks.
    fake_response = _fake_response("model-invented-id", confidence=0.9, verdict="SUPPORTED")

    with patch("verification.verifier.generate_content", return_value=fake_response):
        result = verify_claim(CLAIM, sample_index=0)

    assert result.claim_id == "real-id"


def test_image_only_attached_when_provided():
    fake_response = _fake_response("model-invented-id", confidence=0.9, verdict="SUPPORTED")

    with patch("verification.verifier.generate_content", return_value=fake_response) as mock_generate:
        verify_claim(CLAIM, sample_index=0, image_bytes=b"fake-bytes", image_mime_type="image/png")

    _, kwargs = mock_generate.call_args
    assert len(kwargs["contents"]) == 2  # prompt text + the image part

    with patch("verification.verifier.generate_content", return_value=fake_response) as mock_generate:
        verify_claim(CLAIM, sample_index=0)

    _, kwargs = mock_generate.call_args
    assert len(kwargs["contents"]) == 1  # prompt text only

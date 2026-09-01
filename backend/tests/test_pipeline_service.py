import time
from unittest.mock import patch

import pipeline_service
from shared.models import Claim, VerificationResult


def _claim(claim_id, text, needs_image=False):
    return Claim(claim_id=claim_id, text=text, span_start=0, span_end=0, needs_image=needs_image)


def _collect(gen):
    return list(gen)


def test_zero_claims_short_circuits_without_verifying():
    with patch("pipeline_service.extract_claims", return_value=[]) as mock_extract, \
         patch("pipeline_service.verify_claim") as mock_verify, \
         patch("pipeline_service.synthesize_report") as mock_synthesize:
        events = _collect(pipeline_service.run_fact_check_stream("small talk", "id1"))

    mock_extract.assert_called_once()
    mock_verify.assert_not_called()
    mock_synthesize.assert_not_called()

    assert len(events) == 1
    assert events[0]["event"] == "done"
    assert events[0]["summary"] == pipeline_service.NO_CLAIMS_SUMMARY
    assert events[0]["claims_checked"] == 0


def test_event_order_and_counts_for_multiple_claims():
    claims = [_claim("c1", "claim one"), _claim("c2", "claim two")]

    def fake_verify(claim, sample_index, image_bytes, image_mime_type):
        verdict = "SUPPORTED" if claim.claim_id == "c1" else "REFUTED"
        return VerificationResult(claim_id=claim.claim_id, reasoning="because", confidence=0.9, verdict=verdict)

    with patch("pipeline_service.extract_claims", return_value=claims), \
         patch("pipeline_service.verify_claim", side_effect=fake_verify), \
         patch("pipeline_service.synthesize_report", return_value="a summary"):
        events = _collect(pipeline_service.run_fact_check_stream("some text", "id1"))

    event_types = [e["event"] for e in events]
    assert event_types == ["claims_found", "claim_verified", "claim_verified", "synthesizing", "done"]

    done = events[-1]
    assert done["claims_checked"] == 2
    assert done["supported_count"] == 1
    assert done["refuted_count"] == 1
    assert done["image_verification_calls"] == 0
    # claim_verdicts stays in extraction order regardless of completion order
    assert [cv["claim"]["claim_id"] for cv in done["claim_verdicts"]] == ["c1", "c2"]


def test_final_order_survives_out_of_order_completion():
    # c1 resolves slower than c2, so as_completed() yields c2 first --
    # the final claim_verdicts list must still come back as [c1, c2].
    claims = [_claim("c1", "slow claim"), _claim("c2", "fast claim")]

    def fake_verify(claim, sample_index, image_bytes, image_mime_type):
        if claim.claim_id == "c1":
            time.sleep(0.05)
        return VerificationResult(claim_id=claim.claim_id, reasoning="because", confidence=0.9, verdict="SUPPORTED")

    with patch("pipeline_service.extract_claims", return_value=claims), \
         patch("pipeline_service.verify_claim", side_effect=fake_verify), \
         patch("pipeline_service.synthesize_report", return_value="a summary"):
        events = _collect(pipeline_service.run_fact_check_stream("some text", "id1"))

    verified_order = [e["claim_id"] for e in events if e["event"] == "claim_verified"]
    assert verified_order == ["c2", "c1"]  # c2 really did finish first

    done = events[-1]
    assert [cv["claim"]["claim_id"] for cv in done["claim_verdicts"]] == ["c1", "c2"]  # but final order is restored


def test_needs_image_controls_whether_image_is_passed_to_verification():
    claims = [
        _claim("c1", "about the diagram", needs_image=True),
        _claim("c2", "a general fact", needs_image=False),
    ]
    calls = []

    def fake_verify(claim, sample_index, image_bytes, image_mime_type):
        calls.append((claim.claim_id, image_bytes, image_mime_type))
        return VerificationResult(claim_id=claim.claim_id, reasoning="because", confidence=0.9, verdict="SUPPORTED")

    with patch("pipeline_service.extract_claims", return_value=claims), \
         patch("pipeline_service.verify_claim", side_effect=fake_verify), \
         patch("pipeline_service.synthesize_report", return_value="a summary"):
        events = _collect(pipeline_service.run_fact_check_stream(
            "some text", "id1", image_bytes=b"fake-bytes", image_mime_type="image/png"
        ))

    calls_by_id = {claim_id: (img_bytes, img_mime) for claim_id, img_bytes, img_mime in calls}
    assert calls_by_id["c1"] == (b"fake-bytes", "image/png")
    assert calls_by_id["c2"] == (None, None)

    done = events[-1]
    assert done["image_verification_calls"] == 1


def test_run_fact_check_drains_stream_into_report_and_call_count():
    claims = [_claim("c1", "a claim", needs_image=True)]

    def fake_verify(claim, sample_index, image_bytes, image_mime_type):
        return VerificationResult(claim_id=claim.claim_id, reasoning="because", confidence=0.9, verdict="SUPPORTED")

    with patch("pipeline_service.extract_claims", return_value=claims), \
         patch("pipeline_service.verify_claim", side_effect=fake_verify), \
         patch("pipeline_service.synthesize_report", return_value="a summary"):
        report, image_verification_calls = pipeline_service.run_fact_check(
            "some text", "id1", image_bytes=b"fake-bytes", image_mime_type="image/png"
        )

    assert report.article_id == "id1"
    assert report.claims_checked == 1
    assert report.supported_count == 1
    assert image_verification_calls == 1

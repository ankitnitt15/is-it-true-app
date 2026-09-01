from unittest.mock import patch

from fastapi.testclient import TestClient

import config
import pipeline_service
from limits import rate_limiter
from main import app
from shared.models import Claim, ClaimVerdict, Report

client = TestClient(app)


def _make_report(article_id="abc123", claims_checked=1):
    claim = Claim(claim_id="c1", text="a claim", span_start=0, span_end=0)
    verdict = ClaimVerdict(
        claim=claim, final_verdict="SUPPORTED", confidence=0.9, reasoning="because", source_votes={"SUPPORTED": 1}
    )
    return Report(
        article_id=article_id,
        claims_checked=claims_checked,
        supported_count=1,
        refuted_count=0,
        unverifiable_count=0,
        claim_verdicts=[verdict] if claims_checked else [],
        summary="a summary",
    )


def test_health():
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_check_rejects_empty_input():
    response = client.post("/api/check", data={"text": ""})

    assert response.status_code == 400


def test_check_returns_pipeline_result():
    with patch.object(pipeline_service, "run_fact_check", return_value=(_make_report(), 0)) as mock_run:
        response = client.post("/api/check", data={"text": "a claim to check"})

    mock_run.assert_called_once()
    assert response.status_code == 200
    body = response.json()
    assert body["claims_checked"] == 1
    assert body["from_cache"] is False
    assert body["claim_verdicts"][0]["verdict"] == "SUPPORTED"


def test_check_cache_hit_never_calls_pipeline():
    from cache import report_cache

    report = _make_report(article_id=__import__("hashlib").sha256(b"cached text").hexdigest())
    report_cache.save_report(report.article_id, report)

    with patch.object(pipeline_service, "run_fact_check") as mock_run:
        response = client.post("/api/check", data={"text": "cached text"})

    mock_run.assert_not_called()
    assert response.status_code == 200
    assert response.json()["from_cache"] is True


def test_check_rejected_by_user_cap_never_calls_pipeline():
    with patch.object(rate_limiter, "check_user_cap", return_value=(False, 99)), \
         patch.object(pipeline_service, "run_fact_check") as mock_run:
        response = client.post("/api/check", data={"text": "distinct text for this test"})

    mock_run.assert_not_called()
    assert response.status_code == 429


def test_check_rejected_by_global_cap_never_calls_pipeline():
    with patch.object(rate_limiter, "check_global_cap", return_value=(False, 99)), \
         patch.object(pipeline_service, "run_fact_check") as mock_run:
        response = client.post("/api/check", data={"text": "another distinct text"})

    mock_run.assert_not_called()
    assert response.status_code == 503


def test_check_rejects_bad_image_mime_type():
    response = client.post(
        "/api/check",
        data={"text": ""},
        files={"image": ("not-an-image.txt", b"hello", "text/plain")},
    )

    assert response.status_code == 400


def test_check_rejects_oversized_image():
    import config

    oversized = b"x" * (config.MAX_IMAGE_BYTES + 1)
    response = client.post(
        "/api/check",
        data={"text": ""},
        files={"image": ("big.png", oversized, "image/png")},
    )

    assert response.status_code == 400


def test_check_stream_emits_events_in_order():
    events = [
        {"event": "claims_found", "claims": [{"claim_id": "c1", "text": "a claim"}]},
        {
            "event": "claim_verified", "claim_id": "c1", "claim_text": "a claim",
            "verdict": "SUPPORTED", "confidence": 0.9, "reasoning": "because",
        },
        {"event": "synthesizing"},
        {
            "event": "done", "summary": "a summary", "claims_checked": 1, "supported_count": 1,
            "refuted_count": 0, "unverifiable_count": 0,
            "claim_verdicts": [_make_report().claim_verdicts[0].model_dump()],
            "image_verification_calls": 0,
        },
    ]

    with patch.object(pipeline_service, "run_fact_check_stream", return_value=iter(events)):
        response = client.post("/api/check/stream", data={"text": "a streamed claim"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    lines = [line for line in response.text.split("\n\n") if line.strip()]
    assert len(lines) == 4
    assert '"event": "claims_found"' in lines[0]
    assert '"event": "claim_verified"' in lines[1]
    assert '"event": "synthesizing"' in lines[2]
    assert '"event": "done"' in lines[3]


def test_admin_stats_is_404_when_no_token_configured():
    with patch.object(config, "ADMIN_TOKEN", ""):
        response = client.get("/api/admin/stats", headers={"x-admin-token": "anything"})

    assert response.status_code == 404


def test_admin_stats_rejects_wrong_token():
    with patch.object(config, "ADMIN_TOKEN", "correct-secret"):
        response = client.get("/api/admin/stats", headers={"x-admin-token": "wrong-secret"})

    assert response.status_code == 404


def test_admin_stats_returns_usage_with_correct_token():
    with patch.object(config, "ADMIN_TOKEN", "correct-secret"), \
         patch.object(config, "GLOBAL_DAILY_CALL_CAP", 10):
        rate_limiter.record_global_usage(3)
        response = client.get("/api/admin/stats", headers={"x-admin-token": "correct-secret"})

    assert response.status_code == 200
    body = response.json()
    assert body["global_calls_today"] == 3
    assert body["global_daily_call_cap"] == 10
    assert body["cap_reached"] is False

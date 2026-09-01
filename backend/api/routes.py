import datetime
import hashlib
import json
import logging
import secrets

from fastapi import APIRouter, File, Form, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import StreamingResponse

import config
import image_utils
import pipeline_service
from api.schemas import CheckResponse, ClaimVerdictOut
from cache import report_cache
from limits import identity, rate_limiter
from shared.models import Report

logger = logging.getLogger("isittrue.api")

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/admin/stats")
def admin_stats(x_admin_token: str = Header(default="")):
    # Unset ADMIN_TOKEN means the endpoint is off by default -- 404 rather
    # than 401, so it doesn't even reveal that a stats endpoint exists.
    if not config.ADMIN_TOKEN or not secrets.compare_digest(x_admin_token, config.ADMIN_TOKEN):
        raise HTTPException(404)

    allowed, global_calls_today = rate_limiter.check_global_cap(config.GLOBAL_DAILY_CALL_CAP)
    return {
        "date": datetime.date.today().isoformat(),
        "global_calls_today": global_calls_today,
        "global_daily_call_cap": config.GLOBAL_DAILY_CALL_CAP,
        "cap_reached": not allowed,
    }


@router.post("/check", response_model=CheckResponse)
def check(
    request: Request,
    response: Response,
    text: str = Form(""),
    image: UploadFile | None = File(None),
):
    # Deliberately a sync def, not async: pipeline_service.run_fact_check
    # below is a blocking call (its own ThreadPoolExecutor plus synchronous
    # Gemini calls). FastAPI runs sync route handlers in its own threadpool
    # automatically, which is what keeps that blocking work off the event
    # loop -- an async def here would serialize every request behind it.
    text, image_bytes, image_mime_type, article_id = _prepare(text, image)
    _log_request("/check", article_id, text, image_bytes, image_mime_type)

    cached = report_cache.get_report(article_id)
    if cached is not None:
        logger.info("[%s] cache hit", article_id[:8])
        return _to_response(cached, from_cache=True)

    anon_id = identity.resolve_identity(request, response)
    _check_rate_limits(article_id, anon_id)

    report, image_verification_calls = pipeline_service.run_fact_check(
        text, article_id, image_bytes, image_mime_type
    )

    report_cache.save_report(article_id, report)
    rate_limiter.record_user_usage(anon_id)
    rate_limiter.record_global_usage(_gemini_call_count(report, image_verification_calls))

    _log_response(article_id, report, from_cache=False)
    return _to_response(report, from_cache=False)


@router.post("/check/stream")
def check_stream(
    request: Request,
    text: str = Form(""),
    image: UploadFile | None = File(None),
):
    # Also sync def, for the same reason as /check above.
    text, image_bytes, image_mime_type, article_id = _prepare(text, image)
    _log_request("/check/stream", article_id, text, image_bytes, image_mime_type)

    cached = report_cache.get_report(article_id)
    if cached is not None:
        logger.info("[%s] cache hit", article_id[:8])
        return StreamingResponse(
            iter([_sse_line(_report_to_done_event(cached))]),
            media_type="text/event-stream",
        )

    # Resolve the id before building the StreamingResponse we're about to
    # return, then set the cookie directly on that object -- FastAPI only
    # merges cookies from the injected `response` param into a response it
    # builds itself, not into one a route explicitly constructs and returns
    # (see limits/identity.py).
    anon_id = identity.resolve_id(request)
    _check_rate_limits(article_id, anon_id)

    resp = StreamingResponse(
        _stream_and_persist(text, article_id, image_bytes, image_mime_type, anon_id),
        media_type="text/event-stream",
    )
    identity.set_cookie(resp, anon_id)
    return resp


def _prepare(text: str, image: UploadFile | None) -> tuple[str, bytes | None, str | None, str]:
    """Shared input validation for both endpoints above. Returns (text,
    image_bytes, image_mime_type, article_id); raises HTTPException on
    invalid input."""
    text = text.strip()

    image_bytes: bytes | None = None
    image_mime_type: str | None = None
    if image is not None and image.filename:
        if image.content_type not in config.ALLOWED_IMAGE_MIME_TYPES:
            raise HTTPException(400, "Please attach a JPEG, PNG, or WEBP image.")
        raw_bytes = image.file.read()
        if len(raw_bytes) > config.MAX_IMAGE_BYTES:
            raise HTTPException(
                400,
                f"That image is too large -- please attach one under {_format_size(config.MAX_IMAGE_BYTES)}.",
            )
        image_mime_type = image.content_type
        image_bytes = image_utils.downscale_if_oversized(raw_bytes, image_mime_type)

    if not text and image_bytes is None:
        raise HTTPException(400, "Please paste some text or attach an image to check.")
    if len(text) > config.MAX_INPUT_CHARS:
        raise HTTPException(
            400,
            f"That's too long -- please paste under {config.MAX_INPUT_CHARS} characters at a time.",
        )

    article_id = hashlib.sha256(text.encode() + (image_bytes or b"")).hexdigest()
    return text, image_bytes, image_mime_type, article_id


def _check_rate_limits(article_id: str, anon_id: str) -> None:
    allowed_user, user_count = rate_limiter.check_user_cap(anon_id, config.DAILY_USER_CAP)
    if not allowed_user:
        logger.warning("[%s] rejected: user cap hit (user=%s, count=%d)", article_id[:8], anon_id[:8], user_count)
        raise HTTPException(429, "You've used your free checks for today -- come back tomorrow.")

    allowed_global, global_count = rate_limiter.check_global_cap(config.GLOBAL_DAILY_CALL_CAP)
    if not allowed_global:
        logger.warning("[%s] rejected: global cap hit (count=%d)", article_id[:8], global_count)
        raise HTTPException(503, "This service hit today's usage limit -- please try again tomorrow.")


def _gemini_call_count(report: Report, image_verification_calls: int) -> int:
    # Zero claims -> pipeline_service short-circuits after extraction alone (1 call).
    # Otherwise: 1 extraction call + 1 verification call per claim + 1 synthesis call.
    calls = 1 if report.claims_checked == 0 else report.claims_checked + 2
    # Only claims flagged needs_image actually carried the image during
    # verification (pipeline_service.run_fact_check_stream) -- weight by
    # how many of those calls actually happened, not by claims_checked.
    calls += config.IMAGE_CALL_WEIGHT * image_verification_calls
    return calls


def _stream_and_persist(text, article_id, image_bytes, image_mime_type, anon_id):
    """Forwards each pipeline event to the client as SSE, and once the
    final "done" event has been seen, performs the same cache-save and
    rate-limit bookkeeping the plain /check endpoint does synchronously --
    just triggered from consuming the last event instead of a return value.
    """
    for event in pipeline_service.run_fact_check_stream(text, article_id, image_bytes, image_mime_type):
        yield _sse_line(event)

        if event["event"] == "done":
            report = Report(
                article_id=article_id,
                claims_checked=event["claims_checked"],
                supported_count=event["supported_count"],
                refuted_count=event["refuted_count"],
                unverifiable_count=event["unverifiable_count"],
                claim_verdicts=event["claim_verdicts"],
                summary=event["summary"],
            )
            report_cache.save_report(article_id, report)
            rate_limiter.record_user_usage(anon_id)
            rate_limiter.record_global_usage(_gemini_call_count(report, event["image_verification_calls"]))
            _log_response(article_id, report, from_cache=False)


def _report_to_done_event(report: Report) -> dict:
    return {
        "event": "done",
        "summary": report.summary,
        "claims_checked": report.claims_checked,
        "supported_count": report.supported_count,
        "refuted_count": report.refuted_count,
        "unverifiable_count": report.unverifiable_count,
        "claim_verdicts": [cv.model_dump() for cv in report.claim_verdicts],
        "image_verification_calls": 0,
    }


def _sse_line(event: dict) -> bytes:
    return f"data: {json.dumps(event)}\n\n".encode()


def _log_request(endpoint: str, article_id: str, text: str, image_bytes: bytes | None, image_mime_type: str | None) -> None:
    # Logs metadata only (lengths/presence), never the raw submitted text or
    # image bytes -- forwards can contain sensitive content, and none of it
    # is needed to debug request handling.
    image_desc = f"{image_mime_type}, {len(image_bytes)}b" if image_bytes else "none"
    logger.info(
        "[%s] %s request: text_len=%d image=(%s)",
        article_id[:8], endpoint, len(text), image_desc,
    )


def _log_response(article_id: str, report: Report, from_cache: bool) -> None:
    logger.info(
        "[%s] response: from_cache=%s claims=%d supported=%d refuted=%d unverifiable=%d",
        article_id[:8], from_cache, report.claims_checked,
        report.supported_count, report.refuted_count, report.unverifiable_count,
    )


def _format_size(num_bytes: int) -> str:
    if num_bytes >= 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.1f}MB"
    return f"{num_bytes // 1024}KB"


def _to_response(report: Report, from_cache: bool) -> CheckResponse:
    return CheckResponse(
        summary=report.summary,
        claims_checked=report.claims_checked,
        supported_count=report.supported_count,
        refuted_count=report.refuted_count,
        unverifiable_count=report.unverifiable_count,
        claim_verdicts=[
            ClaimVerdictOut(
                claim_text=cv.claim.text,
                verdict=cv.final_verdict,
                confidence=cv.confidence,
                reasoning=cv.reasoning,
            )
            for cv in report.claim_verdicts
        ],
        from_cache=from_cache,
    )

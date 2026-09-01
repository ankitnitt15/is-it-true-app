from cache import report_cache
from shared.models import Claim, ClaimVerdict, Report


def _make_report(article_id="abc123"):
    claim = Claim(claim_id="c1", text="dummy claim", span_start=0, span_end=0)
    verdict = ClaimVerdict(
        claim=claim,
        final_verdict="SUPPORTED",
        confidence=0.9,
        reasoning="dummy reasoning",
        source_votes={"SUPPORTED": 1},
    )
    return Report(
        article_id=article_id,
        claims_checked=1,
        supported_count=1,
        refuted_count=0,
        unverifiable_count=0,
        claim_verdicts=[verdict],
        summary="dummy summary",
    )


def test_get_report_returns_none_when_not_cached():
    assert report_cache.get_report("nonexistent") is None


def test_save_then_get_round_trips():
    report = _make_report()

    report_cache.save_report(report.article_id, report)
    fetched = report_cache.get_report(report.article_id)

    assert fetched == report


def test_different_article_ids_dont_collide():
    report_cache.save_report("id-1", _make_report("id-1"))

    assert report_cache.get_report("id-2") is None

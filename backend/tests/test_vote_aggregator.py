from shared.models import Claim, VerificationResult
from verification.vote_aggregator import aggregate

CLAIM = Claim(claim_id="c1", text="dummy claim", span_start=0, span_end=0)


def _result(verdict, confidence, reasoning="dummy reasoning"):
    return VerificationResult(claim_id="c1", reasoning=reasoning, confidence=confidence, verdict=verdict)


def test_all_agree_supported():
    verdict = aggregate(CLAIM, [_result("SUPPORTED", 0.9), _result("SUPPORTED", 0.8), _result("SUPPORTED", 0.95)])

    assert verdict.final_verdict == "SUPPORTED"
    assert verdict.source_votes == {"SUPPORTED": 3}


def test_majority_wins_a_split_vote():
    verdict = aggregate(CLAIM, [_result("SUPPORTED", 0.9), _result("SUPPORTED", 0.7), _result("REFUTED", 0.6)])

    assert verdict.final_verdict == "SUPPORTED"
    # confidence is the average of only the agreeing (majority) samples
    assert verdict.confidence == (0.9 + 0.7) / 2


def test_tied_vote_falls_back_to_unverifiable():
    verdict = aggregate(CLAIM, [_result("SUPPORTED", 0.9), _result("REFUTED", 0.8), _result("UNVERIFIABLE", 0.5)])

    assert verdict.final_verdict == "UNVERIFIABLE"
    assert verdict.confidence == 0.0


def test_too_many_failed_samples_falls_back_to_unverifiable():
    verdict = aggregate(CLAIM, [_result("SUPPORTED", 0.9), None, None])

    assert verdict.final_verdict == "UNVERIFIABLE"
    assert verdict.confidence == 0.0

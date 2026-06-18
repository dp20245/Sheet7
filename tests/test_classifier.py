from sheet7_pipeline.classifier import decide
from sheet7_pipeline.schema import ClassifierStatus, ClassifierVote


def test_agreement_promotes_non_noise() -> None:
    result = decide(
        ClassifierVote(label="india_investment", score=90),
        ClassifierVote(label="india_investment", score=80),
        source_reliability_bonus=5,
    )
    assert result.label == "india_investment"
    assert result.status == ClassifierStatus.PROMOTED
    assert result.score >= 60


def test_agreement_rejects_noise() -> None:
    result = decide(
        ClassifierVote(label="boilerplate_or_noise", score=72),
        ClassifierVote(label="boilerplate_or_noise", score=81),
    )
    assert result.status == ClassifierStatus.REJECTED_NOISE


def test_disagreement_needs_research() -> None:
    result = decide(
        ClassifierVote(label="india_investment", score=70),
        ClassifierVote(label="china_plus_one", score=74),
    )
    assert result.status == ClassifierStatus.NEEDS_RESEARCH


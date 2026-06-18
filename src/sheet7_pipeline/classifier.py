from __future__ import annotations

from dataclasses import dataclass

from .schema import ClassifierStatus, ClassifierVote, Confidence, SignalLabel

NOISE: SignalLabel = "boilerplate_or_noise"


@dataclass(frozen=True)
class Classification:
    label: SignalLabel
    score: int
    confidence: Confidence
    status: ClassifierStatus


def decide(
    embedding: ClassifierVote,
    zero_shot: ClassifierVote,
    source_reliability_bonus: int = 0,
) -> Classification:
    if embedding.label == NOISE and zero_shot.label == NOISE:
        score = max(embedding.score, zero_shot.score)
        return Classification(NOISE, score, "high", ClassifierStatus.REJECTED_NOISE)

    blended = min(
        100,
        round((embedding.score * 0.45) + (zero_shot.score * 0.45) + source_reliability_bonus),
    )

    if embedding.label == zero_shot.label and blended >= 60:
        confidence: Confidence = "high" if blended >= 80 else "medium"
        return Classification(embedding.label, blended, confidence, ClassifierStatus.PROMOTED)

    if embedding.label == zero_shot.label:
        return Classification(embedding.label, blended, "low", ClassifierStatus.NEEDS_RESEARCH)

    strong_embedding = embedding.score >= 85 and zero_shot.score < 60
    strong_zero_shot = zero_shot.score >= 85 and embedding.score < 60
    if strong_embedding:
        return Classification(embedding.label, blended, "medium", ClassifierStatus.PROMOTED)
    if strong_zero_shot:
        return Classification(zero_shot.label, blended, "medium", ClassifierStatus.PROMOTED)

    label = embedding.label if embedding.score >= zero_shot.score else zero_shot.label
    return Classification(label, blended, "low", ClassifierStatus.NEEDS_RESEARCH)


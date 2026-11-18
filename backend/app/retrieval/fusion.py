"""Reciprocal Rank Fusion (RRF): merge several ranked lists into one.

Vector search scores are cosine distances; keyword scores are ts_rank values. They're on
different scales, so we can't just add them. RRF ignores the scores and uses only each
item's *position*: an item gets 1 / (k + rank) from every list it appears in.

- Being near the top of either list helps a lot.
- Appearing in both lists helps most.
- k (conventionally 60) dampens the gap between rank 1 and rank 2, so one list can't
  completely dominate.
"""

from collections import defaultdict
from collections.abc import Hashable, Sequence

RRF_K = 60


def reciprocal_rank_fusion[T: Hashable](
    ranked_lists: Sequence[Sequence[T]], k: int = RRF_K
) -> list[tuple[T, float]]:
    """Returns (item, fused score) pairs, best first. Ranks are 1-based."""
    scores: dict[T, float] = defaultdict(float)
    for ranked in ranked_lists:
        for rank, item in enumerate(ranked, start=1):
            scores[item] += 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda pair: pair[1], reverse=True)

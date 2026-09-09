"""Report synthetic search observations; not a correctness acceptance suite.

Run from the repository root with PYTHONPATH=src. No services, files, credentials,
or real matter data are needed. Outputs may change when search slices land.
"""

from dataclasses import replace
import json

from case_intelligence.review_bench_v2 import (
    Candidate,
    DeterministicEmbeddingAdapter,
    DeterministicReranker,
    HybridRetriever,
    InMemoryHybridBackend,
)


def main() -> None:
    matter_id = "matter-synthetic-search-probe"
    candidates = tuple(
        Candidate(matter_id, str(i), str(i), f"synthetic-{i}.txt", 1, value, 1.0)
        for i, value in enumerate(
            ("red bicycle", "blue bicycle", "red truck", "the bicycle is not blue"),
            start=1,
        )
    )
    retriever = HybridRetriever(
        InMemoryHybridBackend(candidates),
        DeterministicEmbeddingAdapter(),
        DeterministicReranker(),
    )
    observations = {
        query: [item.text for item in retriever.search(matter_id, query, limit=20)]
        for query in ("red AND bicycle", "bicycle -blue", '"red bicycle"', "red OR blue")
    }

    class SplitBackend:
        def lexical(self, scope, query, limit):
            return (candidates[0],)

        def dense(self, scope, query_vector, query, limit):
            return (replace(candidates[1], score=0.99),)

    class ControlledReranker:
        def rerank(self, query, rows):
            return tuple(replace(item, score=0.99) for item in rows)

    split_retriever = HybridRetriever(
        SplitBackend(),
        DeterministicEmbeddingAdapter(),
        ControlledReranker(),
        minimum_dense_score=0.72,
        minimum_rerank_score=0.80,
    )
    observations["controlled_split_lanes_with_learned_path_thresholds"] = [
        item.text for item in split_retriever.search(matter_id, "bicycle -blue")
    ]
    many = tuple(
        Candidate(matter_id, str(i), str(i), f"synthetic-{i}.txt", 1, "bicycle", 1.0)
        for i in range(50)
    )
    bounded = HybridRetriever(
        InMemoryHybridBackend(many),
        DeterministicEmbeddingAdapter(),
        DeterministicReranker(),
    )
    observations["requested_30_actual"] = len(bounded.search(matter_id, "bicycle", limit=30))
    print(json.dumps(observations, indent=2))


if __name__ == "__main__":
    main()

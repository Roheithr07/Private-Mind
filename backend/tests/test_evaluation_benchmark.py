import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from backend.benchmarks.evaluate import (
    DATASET_FILE,
    inspect_environment,
    seed_benchmark_data,
    evaluate_retrieval,
    evaluate_end_to_end_chat,
)
from backend.embeddings import get_embedding_provider
from backend.tests.conftest import TestingSessionLocal


def test_benchmark_dataset_integrity():
    """Verify that the benchmark dataset contains all 8 required scenario categories."""
    assert DATASET_FILE.exists()
    with open(DATASET_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "seed_memories" in data
    assert "test_cases" in data
    assert len(data["seed_memories"]) >= 7
    assert len(data["test_cases"]) >= 8

    required_types = {
        "exact_fact_recall",
        "semantic_recall",
        "multi_fact_questions",
        "irrelevant_queries",
        "conflicting_or_outdated_memories",
        "deleted_memories",
        "user_isolation",
        "no_supporting_memory",
    }
    dataset_types = {tc["type"] for tc in data["test_cases"]}
    assert required_types.issubset(dataset_types)


def test_environment_inspection():
    """Verify inference environment and provider detection without secrets."""
    env = inspect_environment()
    assert "platform" in env
    assert "processor" in env
    assert "cpu_count" in env
    assert "gpu_available" in env
    assert "gpu_hardware" in env
    assert "inference_tier" in env
    assert "llm_provider" in env
    assert "llm_model" in env
    assert "vector_backend" in env
    assert "FAISS" in env["vector_backend"]

    # Verify that secrets or API keys are not in environment summary
    env_str = json.dumps(env).lower()
    assert "api_key" not in env_str
    assert "secret" not in env_str


def test_retrieval_benchmarking_and_comparison():
    """Verify reproducible retrieval evaluation and compare semantic vs keyword."""
    with open(DATASET_FILE, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    db = TestingSessionLocal()
    try:
        alias_to_id = seed_benchmark_data(db, dataset)

        # Semantic retrieval
        sem_res = evaluate_retrieval(db, dataset, alias_to_id, search_mode="semantic", limit=5)
        assert sem_res["mean_recall"] >= 0.8
        assert sem_res["mean_mrr"] >= 0.8
        assert sem_res["latency_median_ms"] > 0

        # Keyword retrieval
        kw_res = evaluate_retrieval(db, dataset, alias_to_id, search_mode="keyword", limit=5)

        # Semantic retrieval should achieve higher or equal recall than keyword search
        assert sem_res["mean_recall"] >= kw_res["mean_recall"]
        assert sem_res["mean_precision"] >= kw_res["mean_precision"]
    finally:
        db.close()


def test_embedding_cache_acceleration():
    """Verify query embedding cache improves subsequent lookup latency."""
    emb = get_embedding_provider()
    emb.clear_cache()

    test_query = "What microcontroller is used in the water monitoring system?"

    # Cold lookup
    emb.embed_text(test_query)
    stats1 = emb.get_cache_stats()
    assert stats1["cache_misses"] == 1
    assert stats1["cache_hits"] == 0

    # Warm lookup
    emb.embed_text(test_query)
    stats2 = emb.get_cache_stats()
    assert stats2["cache_hits"] == 1
    assert stats2["hit_ratio"] == 0.5


def test_chat_grounding_comparison():
    """Verify end-to-end chat evaluation comparing memory enabled vs disabled."""
    with open(DATASET_FILE, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    db = TestingSessionLocal()
    try:
        alias_to_id = seed_benchmark_data(db, dataset)

        chat_enabled = evaluate_end_to_end_chat(db, dataset, alias_to_id, memory_enabled=True, limit=5)
        chat_disabled = evaluate_end_to_end_chat(db, dataset, alias_to_id, memory_enabled=False, limit=0)

        assert chat_enabled["grounded_accuracy"] >= 70.0
        assert chat_enabled["total_tokens"] > 0
        assert chat_disabled["total_tokens"] > 0
    finally:
        db.close()

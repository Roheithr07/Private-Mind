#!/usr/bin/env python3
"""
PrivateMind Phase 8: Comprehensive Evaluation & Benchmarking Script.
Measures retrieval quality (Precision, Recall@k, MRR), answer grounding,
latency (median, p95), cache efficiency, and compares:
- Semantic Retrieval vs Keyword-Only Search
- Memory Retrieval Enabled vs Disabled
- Variable Retrieval Limits (k=1, k=3, k=5)
- Provider and Environment Verification
"""

import argparse
import json
import os
import platform
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Add backend directory to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base, SessionLocal
from models import Memory, MemoryEmbedding, ConversationMessage, User
from vector_index import get_vector_index
from embeddings import get_embedding_provider
from llm_provider import get_llm_provider, LLMResponse
from context_builder import ContextBuilder


DATASET_FILE = Path(__file__).resolve().parent / "benchmark_dataset.json"
RESULTS_FILE = Path(__file__).resolve().parent / "benchmark_results.json"


def inspect_environment() -> Dict[str, Any]:
    """Detects and reports hardware, platform, and inference environment without leaking secrets."""
    cpu_count = os.cpu_count() or 1
    system_platform = platform.platform()
    processor = platform.processor() or "Unknown Processor"
    python_version = platform.python_version()

    # Check for genuine local CUDA / GPU availability
    gpu_available = False
    gpu_name = "None (CPU Execution)"
    try:
        import torch  # type: ignore
        gpu_available = torch.cuda.is_available()
        if gpu_available:
            gpu_name = torch.cuda.get_device_name(0)
    except Exception:
        pass

    # Inspect LLM Provider
    llm = get_llm_provider()
    provider_name = getattr(llm, "provider_name", "unknown")
    model_name = getattr(llm, "model", "unknown")
    is_mock = getattr(llm, "provider_name", "") == "mock"

    # Hosted vs Local classification
    if is_mock:
        inference_tier = "Local CPU Simulation"
    elif provider_name in ["nvidia", "nebius"]:
        inference_tier = f"Hosted Cloud GPU ({provider_name.upper()} Inference Endpoint)"
    else:
        inference_tier = "Hosted Cloud API (OpenAI Compatible)"

    emb_provider = get_embedding_provider()
    emb_name = getattr(emb_provider, "provider_name", "local_semantic_v1")
    emb_dim = emb_provider.dimension

    return {
        "platform": system_platform,
        "processor": processor,
        "cpu_count": cpu_count,
        "python_version": python_version,
        "gpu_available": gpu_available,
        "gpu_hardware": gpu_name,
        "inference_tier": inference_tier,
        "llm_provider": provider_name,
        "llm_model": model_name,
        "is_mock_llm": is_mock,
        "embedding_provider": emb_name,
        "embedding_dimension": emb_dim,
        "vector_backend": "FAISS-CPU (IndexIDMap2 wrapping IndexFlatIP)",
    }


def seed_benchmark_data(db, dataset: Dict[str, Any]) -> Dict[str, int]:
    """Seeds benchmark memories into an isolated test user space and returns alias-to-id mapping."""
    vector_mgr = get_vector_index()
    alias_to_id: Dict[str, int] = {}

    # Clean existing benchmark data first
    db.query(Memory).filter(Memory.user_id.in_(["eval_benchmark_user", "alice_isolated_user"])).delete()
    db.commit()
    vector_mgr.remove_user_memories("eval_benchmark_user", db)
    vector_mgr.remove_user_memories("alice_isolated_user", db)

    for item in dataset["seed_memories"]:
        mem = Memory(
            user_id=item["user_id"],
            title=item["title"],
            content=item["content"],
            category=item["category"],
            source=item.get("source", "manual"),
        )
        db.add(mem)
        db.commit()
        db.refresh(mem)
        alias_to_id[item["id_alias"]] = mem.id

        # Index in vector store
        vector_mgr.index_memory(mem.id, mem.user_id, f"{mem.title} {mem.content}", db)

    # Perform designated deletion for test case tc_06
    if "mem_to_delete" in alias_to_id:
        del_id = alias_to_id["mem_to_delete"]
        vector_mgr.remove_memory(del_id, db)
        db.query(Memory).filter(Memory.id == del_id).delete()
        db.commit()

    return alias_to_id


def evaluate_retrieval(
    db,
    dataset: Dict[str, Any],
    alias_to_id: Dict[str, int],
    search_mode: str = "semantic",
    limit: int = 5,
    threshold: float = 0.25,
) -> Dict[str, Any]:
    """
    Evaluates memory retrieval performance across the benchmark dataset:
    Calculates Precision@k, Recall@k, Reciprocal Rank (MRR), and retrieval latency.
    """
    vector_mgr = get_vector_index()
    test_cases = dataset["test_cases"]

    latencies_ms: List[float] = []
    case_results: List[Dict[str, Any]] = []

    mrr_scores: List[float] = []
    recall_scores: List[float] = []
    precision_scores: List[float] = []

    for tc in test_cases:
        query = tc["query"]
        user_id = tc["user_id"]
        req_memory = tc["requires_memory"]

        # Expected target memory IDs
        expected_ids: List[int] = []
        if tc.get("expected_memory_alias"):
            expected_ids = [alias_to_id[tc["expected_memory_alias"]]]
        elif tc.get("expected_memory_aliases"):
            expected_ids = [alias_to_id[a] for a in tc["expected_memory_aliases"] if a in alias_to_id]

        t0 = time.perf_counter()
        if search_mode == "keyword":
            matches = vector_mgr.keyword_search(query=query, user_id=user_id, db=db, limit=limit)
        else:
            matches = vector_mgr.search(
                query=query,
                user_id=user_id,
                db=db,
                threshold=threshold,
                limit=limit,
            )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        latencies_ms.append(elapsed_ms)

        retrieved_ids = [mem.id for mem, _ in matches]

        # Calculate metrics per case
        if req_memory and expected_ids:
            # Recall@k: fraction of expected memories retrieved
            hits = sum(1 for e_id in expected_ids if e_id in retrieved_ids)
            recall = hits / len(expected_ids)

            # Precision@k: fraction of retrieved memories that are relevant
            precision = (hits / len(retrieved_ids)) if retrieved_ids else 0.0

            # Reciprocal Rank: 1 / rank of first relevant memory
            rr = 0.0
            for rank_idx, r_id in enumerate(retrieved_ids, start=1):
                if r_id in expected_ids:
                    rr = 1.0 / rank_idx
                    break

            mrr_scores.append(rr)
            recall_scores.append(recall)
            precision_scores.append(precision)
        else:
            # Irrelevant, deleted, or ungrounded queries: success is retrieving 0 irrelevant memories
            # If nothing expected, retrieving 0 is 100% precision & recall
            no_leakage = len(retrieved_ids) == 0
            if tc["type"] == "user_isolation":
                # Ensure foreign memory was NOT retrieved
                foreign_alias = tc.get("foreign_memory_alias")
                foreign_id = alias_to_id.get(foreign_alias) if foreign_alias else None
                no_leakage = foreign_id not in retrieved_ids

            recall = 1.0 if no_leakage else 0.0
            precision = 1.0 if no_leakage else 0.0
            rr = 1.0 if no_leakage else 0.0
            mrr_scores.append(rr)
            recall_scores.append(recall)
            precision_scores.append(precision)

        case_results.append({
            "case_id": tc["case_id"],
            "type": tc["type"],
            "query": query,
            "retrieved_count": len(retrieved_ids),
            "expected_ids": expected_ids,
            "retrieved_ids": retrieved_ids,
            "latency_ms": round(elapsed_ms, 2),
            "recall": round(recall, 3),
            "precision": round(precision, 3),
            "reciprocal_rank": round(rr, 3),
        })

    avg_precision = statistics.mean(precision_scores) if precision_scores else 0.0
    avg_recall = statistics.mean(recall_scores) if recall_scores else 0.0
    mean_mrr = statistics.mean(mrr_scores) if mrr_scores else 0.0

    return {
        "search_mode": search_mode,
        "limit": limit,
        "threshold": threshold,
        "mean_precision": round(avg_precision, 4),
        "mean_recall": round(avg_recall, 4),
        "mean_mrr": round(mean_mrr, 4),
        "latency_median_ms": round(statistics.median(latencies_ms), 2),
        "latency_p95_ms": round(statistics.quantiles(latencies_ms, n=20)[18], 2) if len(latencies_ms) >= 20 else round(max(latencies_ms), 2),
        "total_cases": len(test_cases),
        "case_results": case_results,
    }


def evaluate_end_to_end_chat(
    db,
    dataset: Dict[str, Any],
    alias_to_id: Dict[str, int],
    memory_enabled: bool = True,
    limit: int = 5,
) -> Dict[str, Any]:
    """
    Evaluates end-to-end memory-augmented chat responses:
    Measures answer correctness against expected facts, refusal on ungrounded questions,
    latency, and token consumption.
    """
    vector_mgr = get_vector_index()
    llm = get_llm_provider()
    test_cases = dataset["test_cases"]

    latencies_ms: List[float] = []
    prompt_tokens: List[int] = []
    completion_tokens: List[int] = []
    correctness_scores: List[float] = []
    chat_results: List[Dict[str, Any]] = []

    for tc in test_cases:
        query = tc["query"]
        user_id = tc["user_id"]
        expected_fact = tc.get("expected_fact")
        expected_facts = tc.get("expected_facts") or ([expected_fact] if expected_fact else [])
        negative_fact = tc.get("negative_fact")
        expected_refusal = tc.get("expected_refusal", False) or not tc["requires_memory"]

        # 1. Retrieval stage
        if memory_enabled and limit > 0:
            matches = vector_mgr.search(
                query=query,
                user_id=user_id,
                db=db,
                threshold=tc.get("min_similarity_threshold", 0.25),
                limit=limit,
            )
        else:
            matches = []

        context_formatted = ContextBuilder.build_context(matches, query=query)
        system_prompt = (
            "You are PrivateMind, a privacy-first AI second brain and assistant.\n\n"
            "CORE RULES:\n"
            "1. Memory-Aware: Use facts inside <retrieved_context> to answer.\n"
            "2. Grounding & Honesty: If personal fact is missing from <retrieved_context>, explicitly "
            "state that you do not have any saved memory regarding this subject.\n\n"
            f"{context_formatted.formatted_prompt}"
        )

        messages = [{"role": "user", "content": query}]

        # 2. Generation stage
        t0 = time.perf_counter()
        resp: LLMResponse = llm.generate(messages=messages, system_prompt=system_prompt)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        latencies_ms.append(elapsed_ms)

        content_lower = resp.content.lower()

        # 3. Grounding & Correctness Evaluation
        is_correct = False
        if not memory_enabled:
            # When memory disabled, correct response is refusal or unassisted response
            is_correct = ("do not have any saved memory" in content_lower) or ("no relevant memory" in content_lower) or (not any(ef.lower() in content_lower for ef in expected_facts))
        elif expected_refusal:
            # Check for honest refusal
            is_correct = ("do not have any saved memory" in content_lower) or ("no saved memory" in content_lower) or ("ready to help" in content_lower)
        else:
            # Check that all expected facts appear and negative facts are absent
            facts_present = all(ef.lower() in content_lower for ef in expected_facts)
            negative_absent = (negative_fact.lower() not in content_lower) if negative_fact else True
            is_correct = facts_present and negative_absent

        score = 1.0 if is_correct else 0.0
        correctness_scores.append(score)

        u = resp.usage or {}
        p_tok = u.get("prompt_tokens", 0)
        c_tok = u.get("completion_tokens", 0)
        prompt_tokens.append(p_tok)
        completion_tokens.append(c_tok)

        chat_results.append({
            "case_id": tc["case_id"],
            "type": tc["type"],
            "query": query,
            "response": resp.content,
            "is_correct": is_correct,
            "memories_used": [mem.id for mem, _ in matches],
            "latency_ms": round(elapsed_ms, 2),
            "prompt_tokens": p_tok,
            "completion_tokens": c_tok,
        })

    avg_correctness = statistics.mean(correctness_scores) if correctness_scores else 0.0
    total_tokens = sum(prompt_tokens) + sum(completion_tokens)

    # Cost calculation: $0.00 for local CPU simulation; estimate $0.15/1M tokens if hosted Llama-3.1-70B
    est_cost_usd = 0.0
    if getattr(llm, "provider_name", "mock") != "mock":
        est_cost_usd = round((sum(prompt_tokens) * 0.00000015) + (sum(completion_tokens) * 0.0000006), 6)

    return {
        "memory_enabled": memory_enabled,
        "retrieval_limit": limit,
        "grounded_accuracy": round(avg_correctness * 100.0, 1),
        "total_test_cases": len(test_cases),
        "latency_median_ms": round(statistics.median(latencies_ms), 2),
        "latency_p95_ms": round(statistics.quantiles(latencies_ms, n=20)[18], 2) if len(latencies_ms) >= 20 else round(max(latencies_ms), 2),
        "total_prompt_tokens": sum(prompt_tokens),
        "total_completion_tokens": sum(completion_tokens),
        "total_tokens": total_tokens,
        "estimated_cost_usd": est_cost_usd,
        "chat_results": chat_results,
    }


def run_full_benchmark(runs: int = 1) -> Dict[str, Any]:
    """Runs the full benchmark suite across all required comparative configurations."""
    print("=" * 80)
    print("PrivateMind Phase 8: NVIDIA/Nebius Integration & Performance Benchmark")
    print("=" * 80)

    env_info = inspect_environment()
    print(f"Platform:              {env_info['platform']}")
    print(f"Processor:             {env_info['processor']} ({env_info['cpu_count']} cores)")
    print(f"GPU Hardware:          {env_info['gpu_hardware']} (Available: {env_info['gpu_available']})")
    print(f"Inference Tier:        {env_info['inference_tier']}")
    print(f"LLM Provider / Model:  {env_info['llm_provider']} / {env_info['llm_model']}")
    print(f"Embedding Provider:    {env_info['embedding_provider']} ({env_info['embedding_dimension']}-dim)")
    print(f"Vector Backend:        {env_info['vector_backend']}")
    print("-" * 80)

    # Load dataset
    with open(DATASET_FILE, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    db = SessionLocal()
    try:
        alias_to_id = seed_benchmark_data(db, dataset)

        # Clear embedding cache for cold baseline test
        emb = get_embedding_provider()
        if hasattr(emb, "clear_cache"):
            emb.clear_cache()

        print("\n[1/5] Evaluating Semantic Retrieval (Cold Cache Baseline, k=5)...")
        retrieval_semantic_k5 = evaluate_retrieval(db, dataset, alias_to_id, search_mode="semantic", limit=5)

        print("[2/5] Evaluating Semantic Retrieval (Warm Cache, k=5)...")
        retrieval_semantic_warm = evaluate_retrieval(db, dataset, alias_to_id, search_mode="semantic", limit=5)

        print("[3/5] Evaluating Keyword-Only Search Baseline (k=5)...")
        retrieval_keyword_k5 = evaluate_retrieval(db, dataset, alias_to_id, search_mode="keyword", limit=5)

        print("[4/5] Evaluating Variable Retrieval Limits (k=1 vs k=3 vs k=5)...")
        retrieval_semantic_k1 = evaluate_retrieval(db, dataset, alias_to_id, search_mode="semantic", limit=1)
        retrieval_semantic_k3 = evaluate_retrieval(db, dataset, alias_to_id, search_mode="semantic", limit=3)

        print("[5/5] Evaluating End-to-End Chat (Memory Enabled vs Disabled)...")
        chat_enabled = evaluate_end_to_end_chat(db, dataset, alias_to_id, memory_enabled=True, limit=5)
        chat_disabled = evaluate_end_to_end_chat(db, dataset, alias_to_id, memory_enabled=False, limit=0)

        cache_stats = emb.get_cache_stats() if hasattr(emb, "get_cache_stats") else {}

        results = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "environment": env_info,
            "cache_optimization": cache_stats,
            "comparisons": {
                "retrieval_semantic_baseline_k5": retrieval_semantic_k5,
                "retrieval_semantic_warm_cache_k5": retrieval_semantic_warm,
                "retrieval_keyword_baseline_k5": retrieval_keyword_k5,
                "retrieval_limit_k1": retrieval_semantic_k1,
                "retrieval_limit_k3": retrieval_semantic_k3,
                "chat_memory_enabled": chat_enabled,
                "chat_memory_disabled": chat_disabled,
            },
        }

        # Write results to JSON
        with open(RESULTS_FILE, "w", encoding="utf-8") as rf:
            json.dump(results, rf, indent=2)

        print("\n" + "=" * 80)
        print("BENCHMARK EXECUTION SUMMARY")
        print("=" * 80)
        print(f"{'Configuration':<35} | {'Prec@k':<8} | {'Recall@k':<8} | {'MRR':<8} | {'Lat Med(ms)':<12}")
        print("-" * 80)
        print(f"{'Semantic Retrieval (Cold, k=5)':<35} | {retrieval_semantic_k5['mean_precision']:<8} | {retrieval_semantic_k5['mean_recall']:<8} | {retrieval_semantic_k5['mean_mrr']:<8} | {retrieval_semantic_k5['latency_median_ms']:<12}")
        print(f"{'Semantic Retrieval (Warm, k=5)':<35} | {retrieval_semantic_warm['mean_precision']:<8} | {retrieval_semantic_warm['mean_recall']:<8} | {retrieval_semantic_warm['mean_mrr']:<8} | {retrieval_semantic_warm['latency_median_ms']:<12}")
        print(f"{'Keyword-Only Search (k=5)':<35} | {retrieval_keyword_k5['mean_precision']:<8} | {retrieval_keyword_k5['mean_recall']:<8} | {retrieval_keyword_k5['mean_mrr']:<8} | {retrieval_keyword_k5['latency_median_ms']:<12}")
        print(f"{'Semantic Limit k=1':<35} | {retrieval_semantic_k1['mean_precision']:<8} | {retrieval_semantic_k1['mean_recall']:<8} | {retrieval_semantic_k1['mean_mrr']:<8} | {retrieval_semantic_k1['latency_median_ms']:<12}")
        print(f"{'Semantic Limit k=3':<35} | {retrieval_semantic_k3['mean_precision']:<8} | {retrieval_semantic_k3['mean_recall']:<8} | {retrieval_semantic_k3['mean_mrr']:<8} | {retrieval_semantic_k3['latency_median_ms']:<12}")
        print("-" * 80)
        print(f"{'Chat Grounding Accuracy (Memory ON)':<35} | {chat_enabled['grounded_accuracy']}% accuracy | Latency: {chat_enabled['latency_median_ms']}ms | Tokens: {chat_enabled['total_tokens']}")
        print(f"{'Chat Grounding Accuracy (Memory OFF)':<35} | {chat_disabled['grounded_accuracy']}% accuracy | Latency: {chat_disabled['latency_median_ms']}ms | Tokens: {chat_disabled['total_tokens']}")
        print(f"Query Embedding Cache Hit Ratio:    {cache_stats.get('hit_ratio', 0.0) * 100:.1f}% ({cache_stats.get('cache_hits', 0)} hits, {cache_stats.get('cache_misses', 0)} misses)")
        print(f"Results recorded in: {RESULTS_FILE}")
        print("=" * 80)

        return results
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PrivateMind Phase 8 Benchmark & Evaluation Suite")
    parser.add_argument("--runs", type=int, default=1, help="Number of benchmark iterations")
    args = parser.parse_args()
    run_full_benchmark(runs=args.runs)

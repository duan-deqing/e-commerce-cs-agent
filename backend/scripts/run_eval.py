"""离线评测脚本：Recall@5 / 引用覆盖率 / 意图正确率 / LLM judge（准确率·幻觉率·忠诚度）。

用法：
    python scripts/run_eval.py                 # 全量评测
    python scripts/run_eval.py --limit 10      # 只跑前 10 条
    python scripts/run_eval.py --regress       # 只跑 badcases.jsonl 回归集
    python scripts/run_eval.py --skip-judge    # 跳过 LLM judge（mock 模式自动跳过）

输出 backend/evals/report.json。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402
from app.core.logging import setup_logging  # noqa: E402

EVALS_DIR = ROOT / "evals"
DATASET = EVALS_DIR / "dataset.jsonl"
BADCASES = EVALS_DIR / "badcases.jsonl"

JUDGE_SYSTEM = """你是严格的客服问答评测 judge。给定【问题】【客服回答】【参考资料】，输出 JSON 判断：
1. correct：回答是否正确回应了问题（资料可支持即正确；资料未覆盖但回答合理说明"无法确定"也算正确）
2. faithful：faithful=回答完全基于资料；partial=部分内容超出资料但无事实冲突；hallucinated=与资料矛盾或编造事实
只输出 JSON，不要其他文字：{"correct": true|false, "faithful": "faithful|partial|hallucinated"}"""


def load_cases(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


async def setup() -> None:
    from app.db import init_db, seed_if_empty
    from app.tools import bootstrap_tools

    init_db()
    seed_if_empty()
    bootstrap_tools()
    from app.rag.vectorstore import ingest_knowledge_dir

    n = await ingest_knowledge_dir()
    print(f"knowledge ingested: {n} chunks")


def _hit(golden_doc_id: str | None, doc_ids: list[str]) -> bool:
    """golden 以文件 stem 前缀匹配（如 thermos-cup 命中 thermos-cup#s0c0）。"""
    if not golden_doc_id:
        return False
    return any(d.startswith(golden_doc_id) for d in doc_ids)


async def run_retrieval_eval(cases: list[dict]) -> dict:
    from app.rag.chain import retrieve

    hits = 0
    scores: list[float] = []
    per_case = []
    for c in cases:
        if not c.get("golden_doc_id"):
            continue
        retrieval = await retrieve(c["question"])
        sources = retrieval.get("sources", [])
        doc_ids = [s.get("doc_id", "") for s in sources]
        top_scores = [float(s.get("score") or 0) for s in sources]
        hit = _hit(c["golden_doc_id"], doc_ids)
        hits += int(hit)
        if top_scores:
            scores.append(max(top_scores))
        per_case.append({"id": c["id"], "hit": hit, "top_doc": doc_ids[0] if doc_ids else None})
    n = len([c for c in cases if c.get("golden_doc_id")]) or 1
    return {
        "recall_at_5": round(hits / n, 4),
        "n": n,
        "hits": hits,
        "avg_top_score": round(sum(scores) / len(scores), 4) if scores else 0.0,
        "per_case": per_case,
    }


async def judge_case(question: str, answer: str, sources: list[dict], tools: list[dict]) -> dict | None:
    """LLM judge：返回 {"correct": bool, "faithful": str}；无资料可判时返回 None。"""
    from app.core.llm import get_llm
    from app.core.config import settings as cfg

    if cfg.use_mock_llm:
        return None
    context_parts = [f"- [{s.get('title')}] {s.get('snippet')}" for s in sources]
    for t in tools:
        if t.get("success"):
            context_parts.append(f"- 工具 {t.get('tool')} 结果: {json.dumps(t.get('data'), ensure_ascii=False, default=str)[:300]}")
    if not context_parts:
        return None
    user = f"【问题】{question}\n【客服回答】{answer}\n【参考资料】\n" + "\n".join(context_parts)
    try:
        llm = get_llm()
        raw = await llm.chat(system=JUDGE_SYSTEM, messages=[{"role": "user", "content": user}], temperature=0.0, max_tokens=100)
        m = raw[raw.index("{") : raw.rindex("}") + 1]
        out = json.loads(m)
        return {"correct": bool(out.get("correct")), "faithful": str(out.get("faithful", "partial"))}
    except Exception as e:  # noqa: BLE001
        print(f"  judge failed: {e}")
        return None


async def run_end2end_eval(cases: list[dict], skip_judge: bool) -> dict:
    from app.agent.orchestrator import orchestrator

    intent_hits = 0
    cite_hits = 0
    cite_n = 0
    judged = 0
    correct = 0
    faithful_n = 0
    hallucinated = 0
    confidence_bins = Counter()
    fallback_n = 0
    latencies: list[float] = []
    per_case: list[dict] = []

    for c in cases:
        t0 = time.perf_counter()
        resp = await orchestrator.handle_message("eval_user", c["question"], session_id=None)
        elapsed = (time.perf_counter() - t0) * 1000
        latencies.append(elapsed)

        intent_ok = resp.get("intent") == c.get("intent")
        intent_hits += int(intent_ok)
        confidence = float(resp.get("confidence") or 0)
        if confidence < 0.4:
            confidence_bins["0-0.4"] += 1
        elif confidence < 0.55:
            confidence_bins["0.4-0.55"] += 1
        elif confidence < 0.8:
            confidence_bins["0.55-0.8"] += 1
        else:
            confidence_bins["0.8-1.0"] += 1
        if resp.get("intent") == "fallback":
            fallback_n += 1

        doc_ids = [s.get("doc_id", "") for s in resp.get("sources", [])]
        if c.get("golden_doc_id"):
            cite_n += 1
            cite_hits += int(_hit(c["golden_doc_id"], doc_ids))

        verdict = None
        if not skip_judge and resp.get("answer"):
            verdict = await judge_case(c["question"], resp["answer"], resp.get("sources", []), resp.get("tools", []))
            if verdict is not None:
                judged += 1
                correct += int(verdict["correct"])
                if verdict["faithful"] == "hallucinated":
                    hallucinated += 1
                    faithful_n += 0
                elif verdict["faithful"] == "partial":
                    faithful_n += 0.5
                else:
                    faithful_n += 1

        per_case.append(
            {
                "id": c["id"],
                "question": c["question"],
                "intent": resp.get("intent"),
                "intent_expected": c.get("intent"),
                "intent_ok": intent_ok,
                "confidence": confidence,
                "sources_n": len(doc_ids),
                "citation_ok": _hit(c.get("golden_doc_id"), doc_ids) if c.get("golden_doc_id") else None,
                "judge": verdict,
                "latency_ms": round(elapsed, 1),
            }
        )
        flag = "" if intent_ok else "  <-- intent mismatch"
        print(f"  [{c['id']}] intent={resp.get('intent')} conf={confidence:.2f} src={len(doc_ids)} {elapsed:.0f}ms{flag}")

    n = len(cases) or 1
    faithfulness = round(faithful_n / judged, 4) if judged else None
    return {
        "intent_accuracy": round(intent_hits / n, 4),
        "citation_coverage": round(cite_hits / cite_n, 4) if cite_n else None,
        "citation_n": cite_n,
        "confidence_histogram": dict(confidence_bins),
        "fallback_rate": round(fallback_n / n, 4),
        "latency_avg_ms": round(sum(latencies) / len(latencies), 1) if latencies else 0,
        "judge": {
            "n": judged,
            "accuracy": round(correct / judged, 4) if judged else None,
            "hallucination_rate": round(hallucinated / judged, 4) if judged else None,
            "faithfulness": faithfulness,
            "skipped": judged == 0,
        },
        "per_case": per_case,
    }


async def main_async(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Offline eval for e-commerce CS agent")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 条")
    parser.add_argument("--regress", action="store_true", help="只跑 badcases.jsonl 回归集")
    parser.add_argument("--skip-judge", action="store_true", help="跳过 LLM judge")
    args = parser.parse_args(argv)

    setup_logging("WARNING")
    await setup()

    src = BADCASES if args.regress else DATASET
    cases = load_cases(src)
    if not cases:
        print(f"no cases in {src}")
        return 1
    if args.limit:
        cases = cases[: args.limit]
    mode = "regress(badcases)" if args.regress else "full"
    print(f"eval mode={mode} cases={len(cases)} prompt_version={settings.prompt_version}")

    print("== retrieval (Recall@5) ==")
    retrieval = await run_retrieval_eval(cases)
    print(f"  recall@5={retrieval['recall_at_5']} hits={retrieval['hits']}/{retrieval['n']}")

    print("== end-to-end ==")
    e2e = await run_end2end_eval(cases, skip_judge=args.skip_judge)
    print(
        f"  intent_acc={e2e['intent_accuracy']} citation_cov={e2e['citation_coverage']} "
        f"fallback_rate={e2e['fallback_rate']} judge={e2e['judge']}"
    )

    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": mode,
        "model": settings.llm_model,
        "prompt_version": settings.prompt_version,
        "cases_n": len(cases),
        "retrieval": retrieval,
        "end2end": e2e,
    }
    report_path = EVALS_DIR / ("report-regress.json" if args.regress else "report.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report -> {report_path}")
    return 0


def main() -> int:
    return asyncio.run(main_async(sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())

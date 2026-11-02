"""Score manually normalized outputs without sending materials to any service.

python -m evaluation.score --dataset evaluation/cases.json --predictions file.json --output report.json
Input: {condition, run_id, dataset_sha256, predictions:[{case_id,prediction}]}.
Missing outputs are errors, never removed from the denominator.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .benchmark import load_dataset
from .metrics import LABELS, summarize


def score(dataset_path, predictions_path):
    dataset, digest = load_dataset(dataset_path)
    submitted = json.loads(Path(predictions_path).read_text(encoding="utf-8"))
    if submitted.get("dataset_sha256") != digest:
        raise ValueError("Dataset hash mismatch; do not compare different input versions")
    gold_by_id = {c["case_id"]: c for c in dataset["cases"]}
    predictions = {}
    for pred in submitted["predictions"]:
        cid = pred["case_id"]
        if cid in predictions or cid not in gold_by_id:
            raise ValueError("Duplicate or unknown case_id")
        if pred.get("prediction") not in (*LABELS, "error"):
            raise ValueError("Invalid prediction label")
        predictions[cid] = pred
    rows = [{"case_id": cid, "gold": case["gold"],
             "prediction": predictions.get(cid, {}).get("prediction", "error")}
            for cid, case in gold_by_id.items()]
    return {"condition": submitted["condition"], "run_id": submitted["run_id"],
            "dataset_sha256": digest, "summary": summarize(rows), "cases": rows,
            "missing_predictions": sorted(set(gold_by_id) - set(predictions)),
            "warning": "先保留模型原始输出，再由盲评者归一化标签；格式错误与超时不可从分母删除。"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = score(args.dataset, args.predictions)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=True))


if __name__ == "__main__":
    main()

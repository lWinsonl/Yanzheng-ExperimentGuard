"""Export model inputs without gold labels; create traceable scoring templates."""
import argparse
import csv
import json
from pathlib import Path
import random

from .benchmark import load_dataset


def prepare(dataset_path, output, seed=20261102):
    dataset, digest = load_dataset(dataset_path)
    output.mkdir(parents=True, exist_ok=True)
    cases = list(dataset["cases"])
    random.Random(seed).shuffle(cases)
    public = [{k: c[k] for k in ("case_id", "domain", "aspect", "claim", "materials")} for c in cases]
    (output / "blind-inputs.json").write_text(json.dumps({"dataset_sha256": digest,
        "case_order_seed": seed, "cases": public}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (output / "gold-do-not-send.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["case_id", "project_id", "gold", "rationale"])
        writer.writeheader()
        writer.writerows({k: c[k] for k in writer.fieldnames} for c in cases)
    # Diagnostic control, not a model output or performance claim.
    baseline = {"condition": "all_insufficient_sanity_control_NOT_A_MODEL", "run_id": "sanity-r1",
                "dataset_sha256": digest,
                "predictions": [{"case_id": c["case_id"], "prediction": "insufficient"} for c in cases]}
    (output / "all-insufficient-control.json").write_text(json.dumps(baseline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return digest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path(__file__).with_name("cases.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(prepare(args.dataset, args.output))

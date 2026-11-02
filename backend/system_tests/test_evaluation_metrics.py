import json

import pytest

from evaluation.benchmark import load_dataset
from evaluation.metrics import cohen_kappa, paired_cluster_bootstrap, summarize, wilson
from evaluation.score import score


def test_oracle_and_all_abstention_do_not_receive_same_quality():
    oracle = [dict(case_id=str(i), gold=label, prediction=label)
              for i, label in enumerate(("supported", "contradicted", "insufficient"))]
    good = summarize(oracle)
    abstain = summarize([{**row, "prediction": "insufficient"} for row in oracle])
    assert good["macro_f1"] == 1
    assert abstain["macro_f1"] == pytest.approx(1 / 6)
    assert abstain["decision_coverage"] == 0
    assert abstain["selective_accuracy"] is None
    assert abstain["anchor_validity"] is None
    assert abstain["unit_accuracy_wilson95"] is None


def test_errors_are_not_dropped_or_treated_as_correct_abstention():
    result = summarize([dict(case_id="x", gold="insufficient", prediction="error")])
    assert result["accuracy"] == 0
    assert result["insufficient_recognition"] == 0
    assert result["execution_error_count"] == 1
    assert result["decision_coverage"] is None


def test_duplicate_cases_are_rejected_instead_of_inflating_n():
    row = dict(case_id="x", gold="supported", prediction="supported")
    with pytest.raises(ValueError, match="Duplicate"):
        summarize([row, row])


def test_wilson_and_degenerate_kappa_have_explicit_denominators():
    assert wilson(0, 0) is None
    assert wilson(0, 10)[1] == pytest.approx(0.2775328, abs=1e-6)
    assert wilson(10, 10)[0] == pytest.approx(0.7224672, abs=1e-6)
    assert cohen_kappa(["a", "b"], ["a", "b"]) == 1
    assert cohen_kappa(["a", "a"], ["a", "a"]) is None


def test_bootstrap_resamples_projects_not_correlated_files_or_runs():
    rows = [dict(project_id="p1", correct_a=True, correct_b=False)] * 10
    rows += [dict(project_id="p2", correct_a=False, correct_b=True)]
    result = paired_cluster_bootstrap(rows, repeats=200, seed=7)
    assert result["projects"] == 2
    assert result["difference"] == 0
    assert result == paired_cluster_bootstrap(rows, repeats=200, seed=7)


def test_missing_predictions_count_as_errors_and_hash_mismatch_is_rejected(tmp_path):
    dataset = tmp_path / "cases.json"
    dataset.write_text(json.dumps({"cases": [{"case_id": "one", "gold": "supported"},
                                            {"case_id": "two", "gold": "contradicted"}]}), encoding="utf-8")
    _, digest = load_dataset(dataset)
    predictions = tmp_path / "predictions.json"
    payload = {"condition": "baseline", "run_id": "r1", "dataset_sha256": digest,
               "predictions": [{"case_id": "one", "prediction": "supported"}]}
    predictions.write_text(json.dumps(payload), encoding="utf-8")
    result = score(dataset, predictions)
    assert result["summary"]["accuracy"] == .5
    assert result["missing_predictions"] == ["two"]
    payload["dataset_sha256"] = "different"
    predictions.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        score(dataset, predictions)


def test_blind_package_does_not_expose_labels_or_rationales(tmp_path):
    from evaluation.prepare import prepare
    dataset = tmp_path / "cases.json"
    dataset.write_text(json.dumps({"cases": [{"case_id": "one", "project_id": "p",
        "domain": "data_model", "aspect": "scope", "claim": "目标", "materials": [],
        "gold": "supported", "rationale": "不要发给模型的金标理由"}]}), encoding="utf-8")
    prepare(dataset, tmp_path / "pack")
    payload = json.loads((tmp_path / "pack/blind-inputs.json").read_text(encoding="utf-8"))
    assert "gold" not in payload["cases"][0]
    assert "rationale" not in payload["cases"][0]

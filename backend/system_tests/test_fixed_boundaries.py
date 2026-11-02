"""Adjacent positive/negative cases for the fixes, not labels copied from the old probe set."""
import copy
import io
import json
import statistics
import zipfile

import pytest

from app.models.review import Finding, FindingLevel
from app.models.version_diff import RevisionAlignmentLevel, VersionDiffStatus
from app.services import claim_graph_service, data_store, evidence_chain, review_service
from app.services.numeric_evidence import evaluate_comparison, evaluate_stability
from app.services.version_diff import version_diff_service
from .conftest import confirm, make_session, upload_text


def comparison():
    return {"main_method": "Alpha", "baseline_method": "Beta", "metric": "RMSE", "better": "lower",
            "main_value": .13, "baseline_value": .21, "test_split": {"main": "test-v4", "baseline": "test-v4"},
            "hardware": "same", "preprocessing": "same", "budget": "same"}


CLAIM = "方法Alpha在本次固定测试中优于基线Beta，仅指表中RMSE点估计。"


def test_numeric_direction_and_equality():
    record = comparison()
    assert evaluate_comparison(record, CLAIM)[0] == "supports"
    record["main_value"] = .3
    assert evaluate_comparison(record, CLAIM)[0] == "contradicts"
    record["main_value"] = record["baseline_value"]
    assert evaluate_comparison(record, CLAIM)[0] == "contradicts"


@pytest.mark.parametrize("field,value", [
    ("main_value", True), ("main_value", float("nan")), ("main_value", float("inf")),
    ("main_value", -.2), ("main_value", "0.13"), ("better", "higher"),
    ("metric", "unregistered_metric"), ("baseline_method", "Gamma"),
    ("test_split", {"main": "fold-A", "baseline": "fold-B"}),
    ("hardware", "different GPUs"), ("budget", None), ("preprocessing", "unknown"),
    ("executed", False), ("is_example", True), ("status", "planned"),
    ("executed", 1), ("status", "unknown"),
])
def test_incomplete_or_inconsistent_observations_abstain(field, value):
    record = comparison()
    record[field] = value
    assert evaluate_comparison(record, CLAIM) is None


@pytest.mark.parametrize("claim", [
    "方法Alpha总体优于基线Beta，未来所有场景更好。",
    "方法Alpha在本次测试中不优于基线Beta。",
    "方法Beta在本次固定测试中优于基线Alpha。",
    "方法Alpha比基线Beta更好。",
])
def test_wrong_or_unbounded_claim_is_not_supported_by_a_table(claim):
    assert evaluate_comparison(comparison(), claim) is None


@pytest.mark.parametrize("metric", ["F1", "F1和RMSE", "未说明的指标"])
def test_record_cannot_support_a_different_or_ambiguous_claim_metric(metric):
    claim = f"方法Alpha在本次固定测试中优于基线Beta，仅指表中{metric}点估计。"
    assert evaluate_comparison(comparison(), claim) is None


def test_json_and_csv_observations_require_confirmation_and_actual_provenance(client):
    sid = make_session(client, CLAIM)
    record = comparison()
    data = upload_text(client, sid, json.dumps({"comparison": record}), "result.json")
    store = data_store.require(sid)
    complete = next(f for f in store.facts.values() if f.source.material_id == data["material_id"] and f.value.startswith("{"))
    for fact in store.facts.values():
        if fact.fact_id != complete.fact_id:
            evidence_chain.confirm_fact(sid, fact.fact_id, "confirm")
    graph = claim_graph_service.build_graph(sid)
    assert not any(e.relation.value == "supports" for e in graph.edges)
    evidence_chain.confirm_fact(sid, complete.fact_id, "confirm")
    assert any(e.relation.value == "supports" for e in claim_graph_service.build_graph(sid).edges)
    store.docs[data["material_id"]].origin = "followup_answer"
    assert not any(e.relation.value == "supports" for e in claim_graph_service.build_graph(sid).edges)

    other = make_session(client, "算法Alpha在本次测试中优于基线Beta，仅指表中latency_ms数值。")
    upload_text(client, other, "task_type,main_method,baseline_method,metric,better,main_value,baseline_value,test_split,hardware,preprocessing,budget\n"
                "comparison,Alpha,Beta,latency_ms,lower,8,12,same,same,same,same\n", "measured.csv")
    confirm(client, other)
    assert any(e.relation.value == "supports" for e in claim_graph_service.build_graph(other).edges)


def test_numeric_contradiction_is_visible_in_main_report(client):
    sid = make_session(client, CLAIM)
    record = comparison()
    record["main_value"] = .5
    upload_text(client, sid, json.dumps({"comparison": record}), "results.json")
    confirm(client, sid)
    report = review_service.run_review(sid)
    assert any(f.rule_id == "numeric_comparison" and f.level == FindingLevel.CONTRADICTION for f in report.findings)


@pytest.mark.parametrize("delimiter,prefix", [(",", "--- 工作表：results ---\n"), ("\t", "正文说明\n")])
def test_office_table_text_keeps_complete_numeric_observations(client, delimiter, prefix):
    import csv
    record = comparison()
    record["task_type"], record["test_split"] = "comparison", "same"
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["task_type"] + [k for k in record if k != "task_type"], delimiter=delimiter)
    writer.writeheader()
    writer.writerow(record)
    sid = make_session(client, CLAIM)
    upload_text(client, sid, prefix + output.getvalue(), "extracted-table.txt")
    confirm(client, sid)
    assert any(e.relation.value == "supports" for e in claim_graph_service.build_graph(sid).edges)


def test_raw_runs_are_recalculated_and_inconsistent_summaries_rejected():
    a, b = [.78, .79, .8, .81, .82], [.7, .75, .8, .85, .9]
    record = dict(main_method="Alpha", baseline_method="Beta", metric="F1", conditions="same", runs=5,
                  main_runs=a, baseline_runs=b)
    claim = "方法Alpha在所报告的这五次运行中比基线Beta更稳定，仅指这五次F1样本标准差较小。"
    result = evaluate_stability(record, claim)
    assert result and result[0] == "supports"
    record["main_std"] = statistics.stdev(a) + .1
    assert evaluate_stability(record, claim) is None
    record.pop("main_std")
    record["runs"] = 1
    assert evaluate_stability(record, claim) is None


def test_stability_rejects_impossible_or_nonfinite_observations():
    claim = "方法Alpha在本次五次运行中比基线Beta更稳定，仅指所报告的F1标准差。"
    record = dict(main_method="Alpha", baseline_method="Beta", metric="F1", conditions="same", runs=5,
                  main_mean=.9, baseline_mean=.8, main_std=.01, baseline_std=.03)
    assert evaluate_stability(record, claim)[0] == "supports"
    assert evaluate_stability(record, claim.replace("F1", "RMSE")) is None
    for field, value in [("main_std", -1), ("main_std", 1), ("runs", True), ("runs", 2.5), ("main_mean", float("inf"))]:
        modified = {**record, field: value}
        assert evaluate_stability(modified, claim) is None


def test_observed_summary_accepts_context_but_rejects_invented_correction(client):
    from app.models.evidence import FactCategory, FactStatus
    from app.services.evidence_checks import observed_repetitions
    sid = make_session(client)
    upload_text(client, sid, "Completed benchmark: F1=0.87 ± 0.02 (5 runs).", "measured.log")
    store = data_store.require(sid)
    fact = next(f for f in store.facts.values()
                if f.category == FactCategory.REPETITION and "±" in f.value)
    assert fact.value != fact.source.snippet
    assert observed_repetitions(fact, store.docs)
    fact.status = FactStatus.CORRECTED
    fact.corrected_value = "0.99 ± 0.001"
    assert not observed_repetitions(fact, store.docs)


def test_snapshot_is_complete_immutable_and_survives_material_replacement(client):
    sid = make_session(client)
    upload_text(client, sid, "F1=0.8\nseed=42", "result.log")
    confirm(client, sid)
    old = review_service.run_review(sid)
    assert len(old.fact_snapshot) == old.usable_fact_count
    old_values = [f.value for f in old.fact_snapshot]
    current = next(iter(data_store.require(sid).facts.values()))
    current.value = "改动后的当前事实"
    evidence_chain.clear_materials(sid, "execution")
    assert [f.value for f in old.fact_snapshot] == old_values
    assert old.material_snapshot


def test_reuploading_same_content_does_not_validate_claimed_change(client):
    sid = make_session(client, "描述本次实验结果")
    upload_text(client, sid, "F1=0.8", "first.log")
    confirm(client, sid)
    first = review_service.run_review(sid)
    upload_text(client, sid, "F1=0.8", "second.log", mode="replace")
    confirm(client, sid)
    alignment = version_diff_service._align_revision("修改了评价指标", first, data_store.require(sid))
    assert alignment.alignment == RevisionAlignmentLevel.NOT_ALIGNED


def test_legacy_snapshot_is_unknown_not_a_false_alignment(client):
    sid = make_session(client)
    old = review_service.run_review(sid)
    old.snapshot_version = 0
    result = version_diff_service._align_revision("修改了指标", old, data_store.require(sid))
    assert result.alignment == RevisionAlignmentLevel.UNKNOWN


def test_duplicate_issue_pairing_stays_uncertain(client):
    sid = make_session(client)
    old = review_service.run_review(sid)
    old.findings = [Finding(rule_id="same_rule", claim_ids=["c"], level=FindingLevel.RISK, title="第一项"),
                    Finding(rule_id="same_rule", claim_ids=["c"], level=FindingLevel.RISK, title="第二项")]
    new = copy.deepcopy(old)
    new.report_id = "new-report"
    for finding in new.findings:
        finding.finding_id += "new"
    result = version_diff_service.compute_diff(sid, old, new)
    assert all(c.status == VersionDiffStatus.INSUFFICIENT_EVIDENCE for c in result.comparisons)


@pytest.mark.parametrize("role,mode", [("results", "append"), ("execution", "delete"), ("", "replace")])
def test_invalid_role_and_mode_do_not_mutate_materials(client, role, mode):
    sid = make_session(client)
    prefix = f"/api/sessions/{sid}"
    response = client.post(prefix + "/materials/text", json={"role": role, "mode": mode, "filename": "record.txt", "content": "F1=0.8"})
    assert response.status_code == 422
    assert client.get(prefix + "/materials").json() == []
    response = client.post(prefix + "/materials/upload", data={"role": role, "mode": mode}, files={"file": ("record.txt", b"F1=0.8")})
    assert response.status_code == 422
    assert client.get(prefix + "/materials").json() == []


def office_file(parts):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        for name, value in parts.items():
            archive.writestr(name, value)
    return stream.getvalue()


def test_docx_extracts_real_paragraphs_and_table_text(client):
    sid = make_session(client)
    raw = office_file({"word/document.xml": '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
        '<w:p><w:r><w:t>计划按设备划分，评价F1。</w:t></w:r></w:p>'
        '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>基线B</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>'})
    result = client.post(f"/api/sessions/{sid}/materials/upload", data={"role": "plan"}, files={"file": ("plan.docx", raw)})
    assert result.status_code == 200
    assert not result.json()["ocr_required"]
    assert result.json()["extracted_facts"]
    doc = data_store.require(sid).docs[result.json()["material_id"]]
    assert "基线B" in doc.content
    assert all(f.source.verify(doc) for f in data_store.require(sid).facts.values())


def test_xlsx_reads_strings_and_sparse_cells_but_does_not_execute_formulas(client):
    sid = make_session(client)
    raw = office_file({
        "xl/workbook.xml": '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="实验结果" r:id="r1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<Relationships><Relationship Id="r1" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/sharedStrings.xml": '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>F1</t></si></sst>',
        "xl/worksheets/sheet1.xml": '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
            '<row><c r="A1" t="s"><v>0</v></c><c r="C1"><v>0.8</v></c></row>'
            '<row><c r="A2"><f>WEBSERVICE("https://example.invalid")</f><v>999</v></c></row></sheetData></worksheet>',
    })
    response = client.post(f"/api/sessions/{sid}/materials/upload", data={"role": "execution"}, files={"file": ("result.xlsx", raw)})
    assert response.status_code == 200
    assert response.json()["ocr_required"]
    content = data_store.require(sid).docs[response.json()["material_id"]].content
    assert "F1,,0.8" in content
    assert "[公式未计算]" in content and "999" not in content


@pytest.mark.parametrize("name,raw", [("bad.docx", b"not a zip"), ("image.png", b"\x89PNG"),
    ("fake.txt", b"PK\x03\x04binary"), ("binary.txt", b"hello\x00world"), ("empty.txt", b"   ")])
def test_unsupported_or_invalid_files_are_explicitly_rejected(client, name, raw):
    sid = make_session(client)
    result = client.post(f"/api/sessions/{sid}/materials/upload", data={"role": "execution"}, files={"file": (name, raw)})
    assert result.status_code == 400
    assert not data_store.require(sid).docs

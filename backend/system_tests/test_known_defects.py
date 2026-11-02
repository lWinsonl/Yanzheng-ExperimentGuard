"""Unfixed acceptance failures. XFAIL is an explicit defect, not a passing test.

Use --runxfail to make these fail normally. Strict mode catches a changed result
so the associated defect and expectations must be reviewed, not silently retired.
"""
import io
import zipfile

import pytest

from app.models.version_diff import RevisionAlignmentLevel, VersionDiffStatus
from app.services import data_store, review_service
from app.services.version_diff import version_diff_service
from .conftest import confirm, make_session, upload_text


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="EG-001 证据类别变化导致同一规则的旧问题被误标为已解决")
def test_same_unresolved_issue_is_not_resolved_when_evidence_category_changes(client):
    sid = make_session(client, "模型A优于基线B")
    first = review_service.run_review(sid)
    old = next(f for f in first.findings if f.rule_id == "dm_baseline")
    upload_text(client, sid, "计划设置基线B", "plan.md", "plan")
    confirm(client, sid)
    result = version_diff_service.run_version_diff(sid, "补充了基线计划，尚未运行")
    assert any(f.rule_id == "dm_baseline" for f in data_store.require(sid).latest_report().findings)
    paired = next(c for c in result.comparisons if c.old_finding_id == old.finding_id)
    assert paired.status != VersionDiffStatus.RESOLVED


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="EG-002 用旧发现引用代替完整旧事实快照，使未修改的指标被报告为新增且理由一致")
def test_unchanged_metric_does_not_validate_revision_claim(client):
    sid = make_session(client, "描述本次实验结果")
    upload_text(client, sid, "F1=0.8", "result.log")
    confirm(client, sid)
    first = review_service.run_review(sid)
    alignment = version_diff_service._align_revision("我已修改评价指标", first, data_store.require(sid))
    assert alignment.alignment != RevisionAlignmentLevel.ALIGNED


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="EG-003 未实现DOCX解析却以普通文本成功接收，未报告解析缺口")
def test_unsupported_docx_is_explicitly_rejected_or_flagged(client):
    sid = make_session(client)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("word/document.xml", "<document>实验计划F1</document>")
    response = client.post(f"/api/sessions/{sid}/materials/upload", data={"role": "plan"},
                           files={"file": ("plan.docx", stream.getvalue())})
    assert response.status_code in (400, 415, 422) or response.json().get("ocr_required") or response.json().get("dropped")


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="EG-004 非法材料角色被静默改成plan，缺少输入枚举校验")
def test_invalid_material_role_is_not_silently_reclassified(client):
    sid = make_session(client)
    response = client.post(f"/api/sessions/{sid}/materials/text", json={
        "role": "results", "filename": "result.log", "content": "F1=0.8"})
    assert response.status_code in (400, 422)


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="EG-005 代码注释中的示例均值标准差被当作实际重复运行结果")
def test_example_numbers_in_code_do_not_replace_observed_runs(client):
    sid = make_session(client, "模型A比基线B更稳定")
    upload_text(client, sid, "# 这里只是未来日志格式示例，并未运行实验\n# F1=0.87 ± 0.02\nseed=42", "example.py")
    confirm(client, sid)
    report = review_service.run_review(sid)
    assert any(f.rule_id == "dm_repetition" for f in report.findings)

"""会话存储:内存为主,JSON 文件做持久化备份。

骨架阶段不引入数据库;接口按仓储模式封装,
后续可替换为 SQLite/PostgreSQL 实现而不影响上层服务。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from app.config import settings
from app.models.claim import ReviewSession
from app.models.claim_graph import ClaimGraph
from app.models.evidence import ExtractedFact, ParsedDocument
from app.models.followup import FollowupQuestion
from app.models.review import RecheckResult, ReviewReport
from app.models.version_diff import (
    ManualReviewLabel,
    MigrationAnswer,
    MigrationQuestion,
    VersionDiffResult,
)


class SessionStore:
    """单会话的聚合根:会话、文档、事实、报告、复查结果、主张-证据图、追问、版本差异、迁移。"""

    def __init__(self, session: ReviewSession):
        self.session = session
        self.docs: dict[str, ParsedDocument] = {}
        self.archived_docs: dict[str, ParsedDocument] = {}
        self.facts: dict[str, ExtractedFact] = {}
        self.reports: dict[str, ReviewReport] = {}
        self.rechecks: dict[str, RecheckResult] = {}
        self.claim_graph: ClaimGraph | None = None
        self.followup_questions: list[FollowupQuestion] = []
        self.version_diffs: list[VersionDiffResult] = []
        self.migration_questions: list[MigrationQuestion] = []
        self.migration_answers: list[MigrationAnswer] = []
        self.manual_labels: list[ManualReviewLabel] = []
        self.baseline_report_id: str = ""
        self.owner_id: str = ""

    # ---- 事实 ----
    def add_fact(self, fact: ExtractedFact) -> None:
        self.facts[fact.fact_id] = fact

    def facts_for_session(self) -> list[ExtractedFact]:
        return list(self.facts.values())

    def usable_facts(self) -> list[ExtractedFact]:
        return [f for f in self.facts.values() if f.is_usable()]

    # ---- 报告 ----
    def add_report(self, report: ReviewReport) -> None:
        self.reports[report.report_id] = report

    def latest_report(self) -> ReviewReport | None:
        if not self.reports:
            return None
        return max(self.reports.values(), key=lambda r: r.created_at)

    # ---- 复查 ----
    def add_recheck(self, recheck: RecheckResult) -> None:
        self.rechecks[recheck.recheck_id] = recheck


class DataStore:
    """全局存储:session_id -> SessionStore,含 JSON 持久化。"""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionStore] = {}
        self._data_dir = Path(settings.data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._restore()

    def _restore(self) -> None:
        """启动时从 JSON 文件恢复历史会话(崩溃/重启后可继续)。"""
        for path in sorted(self._data_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                session = ReviewSession.model_validate(payload["session"])
                store = SessionStore(session)
                store.baseline_report_id = payload.get("baseline_report_id", "")
                store.owner_id = payload.get("owner_id", "")
                for k, v in payload.get("docs", {}).items():
                    store.docs[k] = ParsedDocument.model_validate(v)
                for k, v in payload.get("archived_docs", {}).items():
                    store.archived_docs[k] = ParsedDocument.model_validate(v)
                for k, v in payload.get("facts", {}).items():
                    store.facts[k] = ExtractedFact.model_validate(v)
                for k, v in payload.get("reports", {}).items():
                    store.reports[k] = ReviewReport.model_validate(v)
                for k, v in payload.get("rechecks", {}).items():
                    store.rechecks[k] = RecheckResult.model_validate(v)
                if payload.get("claim_graph"):
                    store.claim_graph = ClaimGraph.model_validate(payload["claim_graph"])
                for fq in payload.get("followup_questions", []):
                    store.followup_questions.append(FollowupQuestion.model_validate(fq))
                for vd in payload.get("version_diffs", []):
                    store.version_diffs.append(VersionDiffResult.model_validate(vd))
                for mq in payload.get("migration_questions", []):
                    store.migration_questions.append(MigrationQuestion.model_validate(mq))
                for ma in payload.get("migration_answers", []):
                    store.migration_answers.append(MigrationAnswer.model_validate(ma))
                for ml in payload.get("manual_labels", []):
                    store.manual_labels.append(ManualReviewLabel.model_validate(ml))
                self._sessions[session.session_id] = store
            except Exception:  # noqa: BLE001
                continue  # 损坏文件跳过,不阻断启动

    def create_session(self, session: ReviewSession) -> SessionStore:
        store = SessionStore(session)
        from app.access import current_owner
        store.owner_id = current_owner.get()
        self._sessions[session.session_id] = store
        self._persist(store)
        return store

    def get(self, session_id: str) -> SessionStore | None:
        return self._sessions.get(session_id)

    def require(self, session_id: str) -> SessionStore:
        store = self.get(session_id)
        if store is None:
            raise KeyError(f"会话不存在:{session_id}")
        return store

    def all_sessions(self) -> list[ReviewSession]:
        from app.access import current_owner
        owner = current_owner.get()
        return [s.session for s in self._sessions.values() if s.owner_id == owner]

    def persist(self, session_id: str) -> None:
        store = self.get(session_id)
        if store:
            self._persist(store)

    def _persist(self, store: SessionStore) -> None:
        """JSON 文件持久化(骨架阶段,崩溃后可恢复)。

        原子写:先写临时文件再 os.replace 替换,避免写入中途崩溃/并发写导致 JSON 损坏。
        """
        path = self._data_dir / f"{store.session.session_id}.json"
        tmp = path.with_suffix(".json.tmp")
        try:
            payload = {
                "session": store.session.model_dump(),
                "baseline_report_id": store.baseline_report_id,
                "owner_id": store.owner_id,
                "docs": {k: v.model_dump() for k, v in store.docs.items()},
                "archived_docs": {k: v.model_dump() for k, v in store.archived_docs.items()},
                "facts": {k: v.model_dump() for k, v in store.facts.items()},
                "reports": {k: v.model_dump() for k, v in store.reports.items()},
                "rechecks": {k: v.model_dump() for k, v in store.rechecks.items()},
                "claim_graph": store.claim_graph.model_dump() if store.claim_graph else None,
                "followup_questions": [q.model_dump() for q in store.followup_questions],
                "version_diffs": [d.model_dump() for d in store.version_diffs],
                "migration_questions": [q.model_dump() for q in store.migration_questions],
                "migration_answers": [a.model_dump() for a in store.migration_answers],
                "manual_labels": [l.model_dump() for l in store.manual_labels],
            }
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, path)  # 原子替换:要么完整旧文件,要么完整新文件
        except OSError:
            try:
                tmp.unlink(missing_ok=True)  # 清理残留临时文件
            except OSError:
                pass
            # 持久化失败不阻断主流程


# 全局单例
data_store = DataStore()

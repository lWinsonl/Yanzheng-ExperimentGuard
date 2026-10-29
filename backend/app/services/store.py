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
from app.models.evidence import ExtractedFact, ParsedDocument
from app.models.review import RecheckResult, ReviewReport


class SessionStore:
    """单会话的聚合根:会话、文档、事实、报告、复查结果。"""

    def __init__(self, session: ReviewSession):
        self.session = session
        self.docs: dict[str, ParsedDocument] = {}
        self.facts: dict[str, ExtractedFact] = {}
        self.reports: dict[str, ReviewReport] = {}
        self.rechecks: dict[str, RecheckResult] = {}

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

    def create_session(self, session: ReviewSession) -> SessionStore:
        store = SessionStore(session)
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
        return [s.session for s in self._sessions.values()]

    def persist(self, session_id: str) -> None:
        store = self.get(session_id)
        if store:
            self._persist(store)

    def _persist(self, store: SessionStore) -> None:
        """JSON 文件持久化(骨架阶段,崩溃后可恢复)。"""
        path = self._data_dir / f"{store.session.session_id}.json"
        try:
            payload = {
                "session": store.session.model_dump(),
                "docs": {k: v.model_dump() for k, v in store.docs.items()},
                "facts": {k: v.model_dump() for k, v in store.facts.items()},
                "reports": {k: v.model_dump() for k, v in store.reports.items()},
                "rechecks": {k: v.model_dump() for k, v in store.rechecks.items()},
            }
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass  # 持久化失败不阻断主流程


# 全局单例
data_store = DataStore()
"""研究主张与审查会话模型。"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from app.models.evidence import new_id


class ExperimentType(str, Enum):
    """实验类型。初版支持两类,各自挂载不同的检查规则集。"""

    DATA_MODEL = "data_model"            # 数据与模型实验
    ALGORITHM_SYSTEM = "algorithm_system"  # 算法与系统性能实验


class Claim(BaseModel):
    """学生写出的研究主张,例如:
    "模型 A 比基线 B 更能预测新设备的故障。"
    """

    claim_id: str = Field(default_factory=lambda: new_id("claim"))
    text: str
    """主张原文。"""

    scope_keywords: list[str] = Field(default_factory=list)
    """从主张中识别的适用范围关键词,例如 ["新设备"]。
    审查规则据此检查测试集是否真的由未见过的设备组成。"""

    experiment_type: ExperimentType = ExperimentType.DATA_MODEL


class ReviewSession(BaseModel):
    """一次审查会话:包含审查范围、全部材料、事实与主张。"""

    session_id: str = Field(default_factory=lambda: new_id("sess"))
    title: str = ""
    experiment_type: ExperimentType = ExperimentType.DATA_MODEL
    claims: list[Claim] = Field(default_factory=list)
    material_ids: list[str] = Field(default_factory=list)
    """按上传顺序记录的材料 ID。"""

    created_at: str = ""
    """ISO 时间,由服务层填充。"""

    def claim_by_id(self, claim_id: str) -> Claim | None:
        for c in self.claims:
            if c.claim_id == claim_id:
                return c
        return None
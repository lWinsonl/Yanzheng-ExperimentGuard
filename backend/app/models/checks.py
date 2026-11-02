"""Bounded program observations, kept separately from model interpretations."""
from typing import Literal

from pydantic import BaseModel, Field


class ProgramCheck(BaseModel):
    check_id: str
    kind: Literal["entity_isolation", "recall_defined", "comparison", "stability"]
    scope_key: str
    scope_identity: str = ""
    title: str
    status: Literal["passed", "failed", "unknown"]
    basis: str
    values: dict = Field(default_factory=dict)
    fact_ids: list[str] = Field(default_factory=list)
    material_ids: list[str] = Field(default_factory=list)
    boundary: str = "仅核对提供的已确认记录，未独立验证记录来源、完整性或其他问题。"


class RepairCheck(BaseModel):
    kind: str
    title: str
    status: Literal["still_fails", "passed_on_records", "scope_unconfirmed", "not_verified"]
    before_check_id: str
    after_check_id: str = ""
    before_values: dict = Field(default_factory=dict)
    after_values: dict = Field(default_factory=dict)
    detail: str

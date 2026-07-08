from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

Metric = Literal["roas", "acos", "budget_consumed", "impressions", "ad_sales"]
Operator = Literal["lt", "lte", "gt", "gte"]
ScopeType = Literal["all", "campaign_type", "campaign"]
ActionType = Literal["pause", "resume", "adjust_budget_pct", "adjust_bid_pct", "alert_only"]
ActionStatus = Literal["pending", "approved", "rejected", "completed"]


class RuleCreate(BaseModel):
    name: str
    is_active: bool = True
    scope_type: ScopeType = "all"
    scope_value: str | None = None
    metric: Metric
    operator: Operator
    threshold: float
    window_days: int = 7
    action_type: ActionType
    action_value: float | None = None


class RuleUpdate(BaseModel):
    name: str | None = None
    is_active: bool | None = None
    scope_type: ScopeType | None = None
    scope_value: str | None = None
    metric: Metric | None = None
    operator: Operator | None = None
    threshold: float | None = None
    window_days: int | None = None
    action_type: ActionType | None = None
    action_value: float | None = None


class RuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    is_active: bool
    scope_type: str
    scope_value: str | None
    metric: str
    operator: str
    threshold: float
    window_days: int
    action_type: str
    action_value: float | None
    created_at: datetime
    updated_at: datetime


class ActionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rule_id: int
    campaign_id: int
    campaign_name: str | None
    metric: str
    metric_value: float
    operator: str
    threshold: float
    action_type: str
    action_value: float | None
    status: str
    reasoning: str
    detected_at: datetime
    resolved_at: datetime | None
    resolved_by: UUID | None


class ActionResolve(BaseModel):
    status: Literal["approved", "rejected", "completed"]


class EvaluateResult(BaseModel):
    new_actions: int

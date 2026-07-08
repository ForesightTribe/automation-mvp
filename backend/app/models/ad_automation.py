import uuid
from datetime import datetime

from sqlalchemy import Index
from sqlmodel import Field, SQLModel

from app.utils.time import now_ist


class AdAutomationRule(SQLModel, table=True):
    """User-defined rule watching ad performance: 'if <metric> <operator>
    <threshold> over <window_days>, recommend <action_type>'. Evaluated by
    `ad_automation_service.evaluate_rules` against the same campaign rollups the
    Ads page uses. Recommendations land in AdAutomationAction — rules never act
    directly."""

    __tablename__ = "ad_automation_rules"

    __table_args__ = (Index("idx_aar_tenant", "tenant_id"),)

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    name: str
    is_active: bool = True
    scope_type: str = "all"  # 'all' | 'campaign_type' | 'campaign'
    scope_value: str | None = None
    metric: str  # 'roas' | 'acos' | 'budget_consumed' | 'impressions' | 'ad_sales'
    operator: str  # 'lt' | 'lte' | 'gt' | 'gte'
    threshold: float
    window_days: int = 7
    action_type: str  # 'pause' | 'resume' | 'adjust_budget_pct' | 'adjust_bid_pct' | 'alert_only'
    action_value: float | None = None
    created_at: datetime = Field(default_factory=now_ist)
    updated_at: datetime = Field(default_factory=now_ist)


class AdAutomationAction(SQLModel, table=True):
    """One recommendation produced by evaluating a rule against a campaign.
    Fields copied from the rule are snapshotted at detection time so later edits
    to the rule don't rewrite history. Phase 1 never executes against Blinkit —
    'approved' means the user will make the change manually; `status` just
    tracks that workflow."""

    __tablename__ = "ad_automation_actions"

    __table_args__ = (
        Index("idx_aaa_tenant_status", "tenant_id", "status"),
        Index("idx_aaa_rule_campaign", "rule_id", "campaign_id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    rule_id: int = Field(foreign_key="ad_automation_rules.id")
    campaign_id: int
    campaign_name: str | None = None
    metric: str
    metric_value: float
    operator: str
    threshold: float
    action_type: str
    action_value: float | None = None
    status: str = "pending"  # 'pending' | 'approved' | 'rejected' | 'completed'
    reasoning: str
    detected_at: datetime = Field(default_factory=now_ist)
    resolved_at: datetime | None = None
    resolved_by: uuid.UUID | None = Field(default=None, foreign_key="users.id")

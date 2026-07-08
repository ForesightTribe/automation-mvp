"""Ad automation: user-defined rules watched against the same per-campaign ad
rollups the Ads page reports (`ads_service`), producing a queue of recommended
actions. Phase 1 never touches Blinkit — resolving an action to 'approved' just
tracks that the user will make the change there manually; there is no
execution path yet (see docs/architecture.md / CLAUDE.md for why: Blinkit's
pause/budget/bid endpoints haven't been reverse-engineered, and the scraper's
write_blocker aborts mutating requests by design)."""
import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import Pagination
from app.models.ad_automation import AdAutomationAction, AdAutomationRule
from app.models.blinkit_marketing import BlinkitAdCampaign, BlinkitAdCampaignDaily
from app.schemas.ad_automation import ActionOut, RuleCreate, RuleUpdate
from app.schemas.common import Page
from app.services.ads_service import _acos, _ad_conds, _roas
from app.utils.time import now_ist

AdDaily = BlinkitAdCampaignDaily

_OPERATORS = {
    "lt": lambda v, t: v < t,
    "lte": lambda v, t: v <= t,
    "gt": lambda v, t: v > t,
    "gte": lambda v, t: v >= t,
}

# pending -> {allowed next statuses}
_TRANSITIONS = {
    "pending": {"approved", "rejected"},
    "approved": {"completed"},
}


# --- Rules CRUD --------------------------------------------------------------

async def list_rules(
    session: AsyncSession, tenant_id: uuid.UUID
) -> list[AdAutomationRule]:
    return (
        await session.execute(
            select(AdAutomationRule)
            .where(AdAutomationRule.tenant_id == tenant_id)
            .order_by(AdAutomationRule.created_at.desc())
        )
    ).scalars().all()


async def create_rule(
    session: AsyncSession, *, tenant_id: uuid.UUID, data: RuleCreate
) -> AdAutomationRule:
    rule = AdAutomationRule(tenant_id=tenant_id, **data.model_dump())
    session.add(rule)
    await session.commit()
    await session.refresh(rule)
    return rule


async def get_rule_for_client(
    session: AsyncSession, *, rule_id: int, tenant_id: uuid.UUID
) -> AdAutomationRule | None:
    rule = await session.get(AdAutomationRule, rule_id)
    if not rule or rule.tenant_id != tenant_id:
        return None
    return rule


async def update_rule(
    session: AsyncSession, *, rule: AdAutomationRule, data: RuleUpdate
) -> AdAutomationRule:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)
    rule.updated_at = now_ist()
    session.add(rule)
    await session.commit()
    await session.refresh(rule)
    return rule


async def delete_rule(session: AsyncSession, *, rule: AdAutomationRule) -> None:
    await session.delete(rule)
    await session.commit()


# --- Evaluation ---------------------------------------------------------------

async def evaluate_rules(session: AsyncSession, tenant_id: uuid.UUID) -> int:
    """Run every active rule for this tenant, inserting a pending
    AdAutomationAction per newly-breaching campaign. Returns the count created."""
    rules = [r for r in await list_rules(session, tenant_id) if r.is_active]
    created = 0
    for rule in rules:
        created += await _evaluate_rule(session, tenant_id=tenant_id, rule=rule)
    return created


async def _scope_campaigns(
    session: AsyncSession, *, tenant_id: uuid.UUID, rule: AdAutomationRule
) -> list[BlinkitAdCampaign]:
    conds = [BlinkitAdCampaign.tenant_id == tenant_id]
    if rule.scope_type == "campaign_type" and rule.scope_value:
        conds.append(BlinkitAdCampaign.type == rule.scope_value)
    elif rule.scope_type == "campaign" and rule.scope_value:
        conds.append(BlinkitAdCampaign.campaign_id == int(rule.scope_value))
    return (await session.execute(select(BlinkitAdCampaign).where(*conds))).scalars().all()


def _metric_value(
    metric: str, budget: float, impressions: int, ad_sales: float
) -> float | None:
    if metric == "budget_consumed":
        return budget
    if metric == "impressions":
        return float(impressions)
    if metric == "ad_sales":
        return ad_sales
    if metric == "roas":
        return _roas(ad_sales, budget)
    if metric == "acos":
        return _acos(budget, ad_sales)
    return None


def _reasoning(rule: AdAutomationRule, value: float, campaign_label: str) -> str:
    op_label = {"lt": "<", "lte": "<=", "gt": ">", "gte": ">="}[rule.operator]
    action_label = rule.action_type.replace("_", " ")
    suffix = (
        f" by {abs(rule.action_value)}%"
        if rule.action_value is not None and "pct" in rule.action_type
        else ""
    )
    return (
        f"{campaign_label}: {rule.metric} {round(value, 2)} {op_label} {rule.threshold} "
        f"over {rule.window_days}d → {action_label}{suffix}"
    )


async def _has_pending_action(
    session: AsyncSession, *, rule_id: int, campaign_id: int
) -> bool:
    return (
        await session.execute(
            select(AdAutomationAction.id).where(
                AdAutomationAction.rule_id == rule_id,
                AdAutomationAction.campaign_id == campaign_id,
                AdAutomationAction.status == "pending",
            )
        )
    ).scalar_one_or_none() is not None


async def _evaluate_rule(
    session: AsyncSession, *, tenant_id: uuid.UUID, rule: AdAutomationRule
) -> int:
    campaigns = await _scope_campaigns(session, tenant_id=tenant_id, rule=rule)
    if not campaigns:
        return 0
    campaign_ids = [c.campaign_id for c in campaigns]
    names = {c.campaign_id: c.name or str(c.campaign_id) for c in campaigns}

    end = now_ist().date()
    start = end - timedelta(days=max(rule.window_days, 1) - 1)
    rows = (
        await session.execute(
            select(
                AdDaily.campaign_id,
                func.coalesce(func.sum(AdDaily.budget_consumed), 0.0),
                func.coalesce(func.sum(AdDaily.impressions), 0),
                func.coalesce(func.sum(AdDaily.ad_sales), 0.0),
            )
            .where(*_ad_conds(tenant_id, start, end, None), AdDaily.campaign_id.in_(campaign_ids))
            .group_by(AdDaily.campaign_id)
        )
    ).all()

    created = 0
    for campaign_id, budget, impressions, ad_sales in rows:
        value = _metric_value(rule.metric, float(budget), int(impressions), float(ad_sales))
        if value is None or not _OPERATORS[rule.operator](value, rule.threshold):
            continue
        if await _has_pending_action(session, rule_id=rule.id, campaign_id=campaign_id):
            continue
        session.add(
            AdAutomationAction(
                tenant_id=tenant_id,
                rule_id=rule.id,
                campaign_id=campaign_id,
                campaign_name=names.get(campaign_id),
                metric=rule.metric,
                metric_value=round(value, 4),
                operator=rule.operator,
                threshold=rule.threshold,
                action_type=rule.action_type,
                action_value=rule.action_value,
                status="pending",
                reasoning=_reasoning(rule, value, names.get(campaign_id, str(campaign_id))),
            )
        )
        created += 1
    if created:
        await session.commit()
    return created


# --- Actions -------------------------------------------------------------------

async def list_actions(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    pagination: Pagination,
    status: str | None = None,
) -> Page[ActionOut]:
    conds = [AdAutomationAction.tenant_id == tenant_id]
    if status:
        conds.append(AdAutomationAction.status == status)
    total = (
        await session.execute(
            select(func.count()).select_from(AdAutomationAction).where(*conds)
        )
    ).scalar_one()
    rows = (
        await session.execute(
            select(AdAutomationAction)
            .where(*conds)
            .order_by(AdAutomationAction.detected_at.desc())
            .offset(pagination.offset)
            .limit(pagination.limit)
        )
    ).scalars().all()
    items = [ActionOut.model_validate(r) for r in rows]
    return Page.build(items, total, pagination)


async def get_action_for_client(
    session: AsyncSession, *, action_id: int, tenant_id: uuid.UUID
) -> AdAutomationAction | None:
    action = await session.get(AdAutomationAction, action_id)
    if not action or action.tenant_id != tenant_id:
        return None
    return action


async def resolve_action(
    session: AsyncSession,
    *,
    action: AdAutomationAction,
    status: str,
    resolved_by: uuid.UUID,
) -> AdAutomationAction:
    allowed = _TRANSITIONS.get(action.status, set())
    if status not in allowed:
        raise ValueError(f"Cannot move an action from '{action.status}' to '{status}'")
    action.status = status
    action.resolved_at = now_ist()
    action.resolved_by = resolved_by
    session.add(action)
    await session.commit()
    await session.refresh(action)
    return action

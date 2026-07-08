"""Ad automation: rules + recommended-action queue. Mounted under
/clients/{client_id}/ad-automation. Phase 1 only — resolving an action never
touches Blinkit; see app/services/ad_automation_service.py."""
import uuid

from fastapi import APIRouter, HTTPException, Query, status

from app.dependencies import ClientDep, CurrentUserDep, PaginationDep, SessionDep
from app.schemas.ad_automation import (
    ActionOut,
    ActionResolve,
    EvaluateResult,
    RuleCreate,
    RuleOut,
    RuleUpdate,
)
from app.schemas.common import Page
from app.services import ad_automation_service

router = APIRouter()


@router.get("/rules", response_model=list[RuleOut])
async def list_rules(session: SessionDep, client: ClientDep):
    return await ad_automation_service.list_rules(session, client.id)


@router.post("/rules", response_model=RuleOut, status_code=status.HTTP_201_CREATED)
async def create_rule(session: SessionDep, client: ClientDep, payload: RuleCreate):
    return await ad_automation_service.create_rule(
        session, tenant_id=client.id, data=payload
    )


@router.put("/rules/{rule_id}", response_model=RuleOut)
async def update_rule(
    session: SessionDep, client: ClientDep, rule_id: int, payload: RuleUpdate
):
    rule = await ad_automation_service.get_rule_for_client(
        session, rule_id=rule_id, tenant_id=client.id
    )
    if not rule:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Rule not found")
    return await ad_automation_service.update_rule(session, rule=rule, data=payload)


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(session: SessionDep, client: ClientDep, rule_id: int):
    rule = await ad_automation_service.get_rule_for_client(
        session, rule_id=rule_id, tenant_id=client.id
    )
    if not rule:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Rule not found")
    await ad_automation_service.delete_rule(session, rule=rule)
    return None


@router.post("/evaluate", response_model=EvaluateResult)
async def evaluate(session: SessionDep, client: ClientDep):
    new_actions = await ad_automation_service.evaluate_rules(session, client.id)
    return EvaluateResult(new_actions=new_actions)


@router.get("/actions", response_model=Page[ActionOut])
async def list_actions(
    session: SessionDep,
    client: ClientDep,
    pagination: PaginationDep,
    status_: str | None = Query(None, alias="status"),
):
    return await ad_automation_service.list_actions(
        session, tenant_id=client.id, pagination=pagination, status=status_
    )


@router.patch("/actions/{action_id}", response_model=ActionOut)
async def resolve_action(
    session: SessionDep,
    client: ClientDep,
    user: CurrentUserDep,
    action_id: int,
    payload: ActionResolve,
):
    action = await ad_automation_service.get_action_for_client(
        session, action_id=action_id, tenant_id=client.id
    )
    if not action:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Action not found")
    try:
        return await ad_automation_service.resolve_action(
            session,
            action=action,
            status=payload.status,
            resolved_by=uuid.UUID(user.user_id),
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))

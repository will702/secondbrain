import uuid
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as OrmSession

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models import AuditLog, Goal, Task, User
from app.models.enums import GoalHorizon, GoalStatus, TaskStatus
from app.services.goals import service as goals
from app.services.policy import check

router = APIRouter(tags=["goals"])


def _own_goal(db: OrmSession, user: User, goal_id: uuid.UUID) -> Goal:
    goal = db.get(Goal, goal_id)
    if goal is None or goal.user_id != user.id:
        raise HTTPException(404, "Goal not found")
    return goal


def _own_task(db: OrmSession, user: User, task_id: uuid.UUID) -> Task:
    task = db.get(Task, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(404, "Task not found")
    return task


def _require(user: User, action: str) -> None:
    if not check(user, action).allowed:
        raise HTTPException(403, f"Your autonomy level does not allow this ({action})")


def _audit(db: OrmSession, user: User, action: str, kind: str, obj_id, detail=None) -> None:
    db.add(
        AuditLog(
            user_id=user.id, actor="user", action=action,
            object_type=kind, object_id=str(obj_id), detail=detail,
        )
    )


@router.get("/goals")
def list_goals(user: User = Depends(get_current_user), db: OrmSession = Depends(get_db)):
    today = goals.local_today(user)
    return {"goals": [goals.goal_view(db, user, g, today) for g in goals.active_goals(db, user, today)]}


class GoalIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    why: str = Field(default="", max_length=300)
    horizon: GoalHorizon = GoalHorizon.week
    metric: str = Field(default="tasks", min_length=1, max_length=50)
    unit: str = Field(default="tasks", min_length=1, max_length=50)
    target_value: float = Field(gt=0, le=10000)
    due_on: date | None = None


@router.post("/goals")
def create_goal(
    body: GoalIn, user: User = Depends(get_current_user), db: OrmSession = Depends(get_db)
):
    """The user creating their own goal is the explicit decision (no proposal needed)."""
    if not check(user, "goal.write").allowed:
        raise HTTPException(403, "Your autonomy level does not allow creating goals")
    today = goals.local_today(user)
    start, week_end = goals.week_bounds(today)
    span = {GoalHorizon.week: week_end, GoalHorizon.month: today + timedelta(days=30),
            GoalHorizon.quarter: today + timedelta(days=90)}
    due = body.due_on or span[body.horizon]
    if due < today:
        raise HTTPException(422, "due_on is in the past")
    goal = Goal(
        user_id=user.id, title=body.title, why=body.why or None, horizon=body.horizon,
        metric=body.metric, unit=body.unit, target_value=body.target_value,
        starts_on=start if body.horizon == GoalHorizon.week else today, due_on=due, source="user",
    )
    db.add(goal)
    db.flush()
    _audit(db, user, "goal.create", "goal", goal.id)
    db.commit()
    return goals.goal_view(db, user, goal, today)


class CheckinIn(BaseModel):
    delta: float = Field(ge=-10000, le=10000)
    note: str | None = Field(default=None, max_length=500)


@router.post("/goals/{goal_id}/checkin")
def goal_checkin(
    goal_id: uuid.UUID, body: CheckinIn,
    user: User = Depends(get_current_user), db: OrmSession = Depends(get_db),
):
    _require(user, "goal.write")
    goal = _own_goal(db, user, goal_id)
    if body.delta == 0:
        raise HTTPException(422, "delta must not be zero")
    goals.record_checkin(db, user, goal, body.delta, body.note)
    return goals.goal_view(db, user, goal)


class StatusIn(BaseModel):
    status: GoalStatus


@router.post("/goals/{goal_id}/status")
def set_goal_status(
    goal_id: uuid.UUID, body: StatusIn,
    user: User = Depends(get_current_user), db: OrmSession = Depends(get_db),
):
    _require(user, "goal.write")
    goal = _own_goal(db, user, goal_id)
    goal.status = body.status
    _audit(db, user, "goal.status", "goal", goal.id, {"status": body.status.value})
    db.commit()
    return goals.goal_view(db, user, goal)


@router.post("/goals/suggest")
def suggest_goals(user: User = Depends(get_current_user), db: OrmSession = Depends(get_db)):
    """Create this week's target suggestions as pending proposals (nothing is set yet)."""
    created = goals.propose_targets(db, user)
    return {
        "proposals": [
            {"proposal_id": str(p.id), "payload": p.payload, "evidence": p.evidence}
            for p in created
        ]
    }


@router.get("/goals/review")
def goals_review(user: User = Depends(get_current_user), db: OrmSession = Depends(get_db)):
    return goals.weekly_review(db, user)


@router.post("/tasks/{task_id}/complete")
def complete_task(
    task_id: uuid.UUID, user: User = Depends(get_current_user), db: OrmSession = Depends(get_db)
):
    _require(user, "task.create")
    task = _own_task(db, user, task_id)
    if task.status != TaskStatus.done:
        task.status = TaskStatus.done
        task.completed_at = datetime.now(UTC)
        _audit(db, user, "task.complete", "task", task.id)
        db.commit()
    return {"id": str(task.id), "status": task.status.value, "goal_id": str(task.goal_id) if task.goal_id else None}


class TaskGoalIn(BaseModel):
    goal_id: uuid.UUID | None


@router.post("/tasks/{task_id}/goal")
def link_task_goal(
    task_id: uuid.UUID, body: TaskGoalIn,
    user: User = Depends(get_current_user), db: OrmSession = Depends(get_db),
):
    _require(user, "goal.write")
    task = _own_task(db, user, task_id)
    if body.goal_id is not None:
        _own_goal(db, user, body.goal_id)  # 404 for someone else's goal
    task.goal_id = body.goal_id
    _audit(db, user, "task.link_goal", "task", task.id, {"goal_id": str(body.goal_id) if body.goal_id else None})
    db.commit()
    return {"id": str(task.id), "goal_id": str(task.goal_id) if task.goal_id else None}

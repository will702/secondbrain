"""Action/permission policy layer (SECURITY.md §3).

Every mutating operation flows through Policy.check — there is deliberately no
code path that bypasses it. Levels 0–4 gate capability; the danger list is
confirmation-gated at EVERY level.
"""

from dataclasses import dataclass

from app.models import User

# Always require explicit confirmation regardless of autonomy level.
DANGER_ACTIONS = {
    "send_email",
    "delete_event_hard",
    "delete_document",
    "meeting.invite",  # emails other people from the user's account
    "integration.disconnect",
    "permission.change",
    "account.delete",
}

LEVEL_CAPABILITIES = {
    0: set(),  # Observer: read-only
    1: {"task.create", "note.create", "review.resolve", "goal.write"},  # Assistant
    2: {"task.create", "note.create", "review.resolve", "event.write_soft", "goal.write"},  # Planner
    3: {  # Copilot
        "task.create",
        "note.create",
        "review.resolve",
        "goal.write",
        "event.write_soft",
        "event.write_hard",
        "email.draft",
        "shortcut.run",
    },
    4: {  # Autonomous: same as 3 + no per-action confirmation for non-danger actions
        "task.create",
        "note.create",
        "review.resolve",
        "goal.write",
        "event.write_soft",
        "event.write_hard",
        "email.draft",
        "shortcut.run",
    },
}


@dataclass
class PolicyDecision:
    allowed: bool
    requires_confirmation: bool
    reason: str


def check(user: User, action: str) -> PolicyDecision:
    if action in DANGER_ACTIONS:
        return PolicyDecision(
            allowed=True,  # may be performed — but only interactively, via proposals
            requires_confirmation=True,
            reason=f"'{action}' is on the danger list: explicit user confirmation is always required",
        )
    capabilities = LEVEL_CAPABILITIES.get(user.autonomy_level, set())
    if action in capabilities:
        requires_confirmation = user.autonomy_level < 4
        return PolicyDecision(
            allowed=True,
            requires_confirmation=requires_confirmation,
            reason=(
                f"autonomy level {user.autonomy_level} permits '{action}'"
                + (
                    ""
                    if not requires_confirmation
                    else "; confirmation still required below level 4"
                )
            ),
        )
    return PolicyDecision(
        allowed=False,
        requires_confirmation=False,
        reason=f"autonomy level {user.autonomy_level} does not permit '{action}' "
        f"(requires a higher level)",
    )

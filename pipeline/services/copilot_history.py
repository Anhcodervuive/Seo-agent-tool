"""Cursor-based, bounded reads for the persisted Copilot conversation history."""

from app.models import CopilotMessage


DEFAULT_COPILOT_MESSAGE_PAGE_SIZE = 30
MAX_COPILOT_MESSAGE_PAGE_SIZE = 50


def get_copilot_message_page(
    conversation_id,
    *,
    before_message_id=None,
    after_message_id=None,
    limit=DEFAULT_COPILOT_MESSAGE_PAGE_SIZE,
):
    """Return one chronological message page without offset scans.

    An initial request returns the most recent page. ``before_message_id``
    retrieves older history, while ``after_message_id`` retrieves only newly
    appended messages for the polling path.
    """
    if before_message_id and after_message_id:
        raise ValueError("Use either before_message_id or after_message_id, not both.")
    limit = max(1, min(int(limit), MAX_COPILOT_MESSAGE_PAGE_SIZE))
    query = CopilotMessage.query.filter(
        CopilotMessage.conversation_id == conversation_id,
        CopilotMessage.role.in_(("user", "assistant", "system")),
    )

    if after_message_id:
        rows = (
            query.filter(CopilotMessage.id > after_message_id)
            .order_by(CopilotMessage.id.asc())
            .limit(limit + 1)
            .all()
        )
        has_newer = len(rows) > limit
        rows = rows[:limit]
        mode, has_older = "after", None
    else:
        if before_message_id:
            query = query.filter(CopilotMessage.id < before_message_id)
            mode = "before"
        else:
            mode = "latest"
        rows = query.order_by(CopilotMessage.id.desc()).limit(limit + 1).all()
        has_older = len(rows) > limit
        rows = list(reversed(rows[:limit]))
        has_newer = False

    return {
        "messages": rows,
        "page": {
            "mode": mode,
            "limit": limit,
            "has_older": has_older,
            "has_newer": has_newer,
            "oldest_message_id": rows[0].id if rows else None,
            "newest_message_id": rows[-1].id if rows else None,
        },
    }

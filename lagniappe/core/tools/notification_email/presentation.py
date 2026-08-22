"""Notification-email copy, grouping, multipart rendering, and sending."""

from html import escape

from lagniappe import CONFIG

from .. import auth_email
from ..database import notification_email as email_database
from . import links
from .capture import DOCUMENT_MENTION_EVENT, TASK_ASSIGNMENT_EVENT


# @testable false
# @covered-by lagniappe/core/tools/notification_email/delivery.py::deliver
# @reason generic copy selection is exercised through delivery
def _generic(item, _app_name):
    return {
        "subject": None,
        "title": str(item.get("title") or "Notification"),
        "text": str(item.get("body") or ""),
        "html": escape(str(item.get("body") or "")),
        "standalone_headings": True,
    }


# @testable false
# @covered-by lagniappe/core/tools/notification_email/delivery.py::deliver
# @reason mention-specific copy is exercised through delivery
def _document_mention(item, app_name):
    document_name = str(item.get("document_name") or "document")
    return {
        "subject": f"{app_name} document mention",
        "title": "Document mention",
        "text": f"You were mentioned in the {document_name} document.",
        "html": f"You were mentioned in the <i>{escape(document_name)}</i> document.",
        "standalone_headings": False,
    }


# @testable false
# @covered-by lagniappe/core/tools/notification_email/delivery.py::deliver
# @reason assignment-specific copy is exercised through delivery
def _task_assignment(item, app_name):
    sender_name = str(item.get("sender_name") or "A user")
    task_name = str(item.get("task_name") or "task")
    return {
        "subject": f"Task assigned on {app_name}",
        "title": "Task assigned",
        "text": f"{sender_name} assigned you the task {task_name}.",
        "html": (
            f"{escape(sender_name)} assigned you the task "
            f"<i>{escape(task_name)}</i>."
        ),
        "standalone_headings": False,
    }


EVENT_PRESENTATIONS = {
    DOCUMENT_MENTION_EVENT: _document_mention,
    TASK_ASSIGNMENT_EVENT: _task_assignment,
}


# @testable false
# @covered-by lagniappe/core/tools/notification_email/delivery.py::deliver
# @reason type dispatch is exercised through delivery
def presentation(item, app_name):
    renderer = EVENT_PRESENTATIONS.get(item.get("event_type"), _generic)
    return renderer(item, app_name)


# @testable false
# @covered-by lagniappe/core/tools/notification_email/delivery.py::deliver
# @reason sender grouping is exercised through digest delivery
def group_digest_messages(items):
    grouped = []
    by_sender = {}
    for item in items:
        if item.get("source_type") != "message":
            grouped.append(item)
            continue
        sender = item.get("sender")
        sender_name = str(item.get("sender_name") or "a user")
        sender_id = (
            email_database.encoded_key(sender)
            if sender is not None
            else sender_name.casefold()
        )
        existing = by_sender.get(sender_id)
        if existing is None:
            existing = dict(item)
            existing["title"] = f"Messages from {sender_name}"
            grouped.append(existing)
            by_sender[sender_id] = existing
            continue
        bodies = [existing.get("body"), item.get("body")]
        existing["body"] = "\n\n".join(
            str(body).strip() for body in bodies if str(body or "").strip()
        )
    return grouped


# @testable false
# @covered-by lagniappe/core/tools/notification_email/delivery.py::deliver
# @reason multipart rendering is exercised through delivery
def render_email(subject, items, *, digest=False, overflow=0):
    app_name = str(getattr(CONFIG, "APP_NAME", "Lagniappe") or "Lagniappe")
    if digest:
        items = group_digest_messages(items)
    presentations = [presentation(item, app_name) for item in items]
    concise = bool(
        not digest
        and len(presentations) == 1
        and not presentations[0]["standalone_headings"]
    )
    text_lines = [] if concise or digest else [subject, ""]
    html_items = []
    for item, item_presentation in zip(items, presentations, strict=True):
        url = links.absolute_url(item.get("target_path"))
        if concise:
            text_lines.extend((item_presentation["text"], url, ""))
        else:
            text_lines.append(item_presentation["title"])
            if item_presentation["text"]:
                text_lines.append(item_presentation["text"])
            text_lines.extend((url, ""))
        title_html = (
            ""
            if concise
            else (
                '<h2 style="font-size:16px;margin:0 0 6px">'
                f"{escape(item_presentation['title'])}</h2>"
            )
        )
        body_html = (
            '<div style="white-space:pre-wrap;margin:0 0 6px">'
            f"{item_presentation['html']}</div>"
            if item_presentation["html"]
            else ""
        )
        html_items.append(
            '<section style="margin:0 0 18px">'
            f"{title_html}{body_html}"
            f'<a href="{escape(url, quote=True)}">Open in {escape(app_name)}</a>'
            "</section>"
        )
    if overflow:
        noun = "item is" if overflow == 1 else "items are"
        notice = f"{overflow} more {noun} available in {app_name}."
        text_lines.extend((notice, links.absolute_url("/"), links.absolute_url("/messages")))
        html_items.append(
            f"<p>{escape(notice)} "
            f'<a href="{escape(links.absolute_url("/"), quote=True)}">Notifications</a> · '
            f'<a href="{escape(links.absolute_url("/messages"), quote=True)}">Messages</a></p>'
        )
    heading_html = (
        ""
        if concise or digest
        else f'<h1 style="font-size:20px;margin:0 0 18px">{escape(subject)}</h1>'
    )
    html = (
        '<div style="font-family:system-ui,-apple-system,sans-serif;'
        'font-size:15px;line-height:1.45;color:#222;max-width:680px">'
        f"{heading_html}{''.join(html_items)}</div>"
    )
    return "\n".join(text_lines).strip(), html


# @testable false
# @covered-by lagniappe/core/tools/notification_email/delivery.py::deliver
# @reason SMTP composition is exercised through delivery
def send(user, row, items, *, digest=False, overflow=0):
    app_name = str(getattr(CONFIG, "APP_NAME", "Lagniappe") or "Lagniappe")
    row_presentation = presentation(row, app_name)
    if digest:
        subject = f"{app_name} daily digest"
    elif row_presentation["subject"]:
        subject = row_presentation["subject"]
    elif (
        row.get("source_type") == "message"
        or row.get("record_type") == "message-candidate"
    ):
        subject = f"New messages on {app_name}"
    else:
        subject = f"New notification from {app_name}"
    text_body, html_body = render_email(
        subject, items, digest=digest, overflow=overflow
    )
    return auth_email.send_email(
        user.email,
        subject,
        text_body,
        html_body,
        message_id=links.message_id(row),
    )

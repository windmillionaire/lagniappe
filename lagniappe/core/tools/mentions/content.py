"""Checkpoint mention validation, saved-node extraction, and public text."""

from typing import TypedDict

from bs4 import BeautifulSoup
from bs4.element import NavigableString

from ...properties import mention


class SavedMention(TypedDict):
    recipient: str
    display_name: str


class MentionOccurrence(SavedMention):
    occurrence_id: str


def validate_mentions_payload(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, list) or len(value) > mention.MAX_MENTIONS_PER_CHECKPOINT:
        return "Document mentions must be a bounded list."
    for occurrence in value:
        if not isinstance(occurrence, dict):
            return "Document mention must be an object."
        if not mention.valid_occurrence_id(occurrence.get("occurrence_id")):
            return "Document mention occurrence is invalid."
        if not mention.valid_recipient(
            occurrence.get("recipient")
        ) or not mention.valid_display_name(occurrence.get("display_name")):
            return "Document mention recipient is invalid."
    return None


def saved_mentions(html: str | None) -> dict[str, SavedMention]:
    soup = BeautifulSoup(html or "", "html.parser")
    saved: dict[str, SavedMention] = {}
    for node in soup.select('[data-type="lagniappe-mention"][data-mention-id]'):
        occurrence_id = node.get("data-mention-id")
        recipient = node.get("data-recipient")
        display_name = node.get("data-display-name")
        if (isinstance(occurrence_id, str) and occurrence_id and isinstance(recipient, str)
                and recipient and isinstance(display_name, str) and display_name):
            saved[occurrence_id] = {
                "recipient": recipient,
                "display_name": display_name,
            }
    return saved


def sanitize_mentions(html: str) -> str:
    """Render mention nodes as inert plain @Name text for public/export HTML."""
    if not html:
        return html
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.select('[data-type="lagniappe-mention"]'):
        name = mention.public_display_name(
            node.get("data-display-name") or node.get_text()
        )
        node.replace_with(NavigableString(f"@{name}" if name else "@"))
    return str(soup)

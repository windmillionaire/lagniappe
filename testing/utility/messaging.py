from config import SETTINGS


def simulate_window_message(user, message_type, data):
    """
    Dispatch the browser event that app code consumes after FCM parsing.

    Args:
        user: The test user
        message_type: The event type (e.g., "server-change", "sync-update")
        data: The message payload
    """
    user.page.evaluate(
        """({ messageType, data }) => {
            window.dispatchEvent(new CustomEvent(messageType, { detail: data }));
        }""",
        {"messageType": message_type, "data": data},
    )


def simulate_fcm_message(user, message_type, data):
    """
    Simulate an FCM/service-worker message reaching the browser window.

    The production service worker posts ``{ type, message }`` to
    ``navigator.serviceWorker``. ``src/script/main.mjs`` parses that payload
    and redispatches ``window`` events for the view layer.
    """
    user.page.evaluate(
        """({ messageType, data, protocol, protocolVersion }) => {
            const payload = {
                protocol,
                protocol_version: String(protocolVersion),
                type: messageType,
                message: JSON.stringify(data),
            };
            if (navigator.serviceWorker?.dispatchEvent) {
                navigator.serviceWorker.dispatchEvent(
                    new MessageEvent("message", { data: payload }),
                );
                return;
            }
            window.dispatchEvent(new CustomEvent(messageType, { detail: data }));
        }""",
        {
            "messageType": message_type,
            "data": data,
            "protocol": SETTINGS.BROWSER_PROTOCOL["id"],
            "protocolVersion": SETTINGS.BROWSER_PROTOCOL["version"],
        },
    )


def simulate_collaboration_message(user, message_type, data):
    """Backward-compatible name for service-worker-style message simulation."""
    simulate_fcm_message(user, message_type, data)

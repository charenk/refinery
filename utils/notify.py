"""macOS desktop notification helper.

Calls `osascript` to display a system notification. The function fails silently:
no caller should ever crash because a notification could not be shown.

Security note: AppleScript string literals can be broken (or escape into shell)
by unescaped double quotes and backslashes in the title or message. We escape
both characters and strip newlines before building the script. We also cap
length, since macOS truncates notifications anyway.
"""

import logging
import subprocess

logger = logging.getLogger(__name__)

_MAX_TITLE_LENGTH = 80
_MAX_MESSAGE_LENGTH = 240


def _escape_for_applescript(text: str) -> str:
    """Make `text` safe to embed inside an AppleScript double-quoted string."""
    if text is None:
        return ""
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", " ")
        .replace("\r", " ")
    )


def notify(title: str, message: str) -> None:
    """Show a macOS desktop notification. Fails silently on any error."""
    safe_title = _escape_for_applescript(title)[:_MAX_TITLE_LENGTH]
    safe_message = _escape_for_applescript(message)[:_MAX_MESSAGE_LENGTH]

    applescript = f'display notification "{safe_message}" with title "{safe_title}"'

    try:
        subprocess.run(
            ["osascript", "-e", applescript],
            check=True,
            capture_output=True,
            timeout=5,
        )
    except Exception as error:
        logger.warning("Notification failed: %s", error)

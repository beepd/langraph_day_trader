"""
Telegram notifications. Sending a message never stops the app: any problem is logged and ignored.

.env settings:
    TELEGRAM_BOT_TOKEN=...   (from BotFather)
    TELEGRAM_CHAT_ID=...     (your chat with the bot)
    TELEGRAM_ENABLED=0       (optional: mute all messages, e.g. while testing)
"""
import html
import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger("notify")

MAX_LENGTH = 4000          # Telegram refuses messages longer than 4096 characters
_warned_missing = False


def esc(value) -> str:
    """Make any text safe to put inside an HTML message (headlines contain characters like & and <)."""
    return html.escape(str(value), quote=False)


def _chunks(message: str) -> list[str]:
    """Split a long message at line breaks so every piece fits Telegram's limit."""
    parts, current = [], ""
    for line in message.split("\n"):
        while len(line) > MAX_LENGTH:                       # one absurdly long line: cut it
            if current:
                parts.append(current)
                current = ""
            parts.append(line[:MAX_LENGTH])
            line = line[MAX_LENGTH:]
        if current and len(current) + len(line) + 1 > MAX_LENGTH:
            parts.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        parts.append(current)
    return parts or [""]


def _post(token: str, chat_id: str, text: str, html_mode: bool) -> bool:
    fields = {"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"}
    if html_mode:
        fields["parse_mode"] = "HTML"
    request = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage",
                                     data=urllib.parse.urlencode(fields).encode("utf-8"))
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status == 200
    except urllib.error.HTTPError as error:
        try:
            detail = json.loads(error.read().decode("utf-8")).get("description", "")
        except Exception:
            detail = ""
        if html_mode and error.code == 400 and "parse" in detail.lower():
            log.warning("Telegram could not read the formatting; sending the message as plain text")
            return _post(token, chat_id, html.unescape(re.sub(r"<[^>]+>", "", text)), False)
        log.error("Telegram rejected the message (HTTP %s): %s", error.code, detail)   # never log the URL: it holds the token
        return False
    except Exception as error:
        log.error("Telegram notification failed (non-fatal): %s", type(error).__name__)
        return False


def send_telegram(message: str) -> bool:
    """Send a message (HTML allowed: <b>, <i>, <code>). Never raises. Returns True if everything was sent."""
    global _warned_missing
    if os.environ.get("TELEGRAM_ENABLED", "1").strip().lower() in {"0", "false", "no", "off"}:
        return False
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        if not _warned_missing:
            log.warning("Telegram credentials missing: notifications are off.")
            _warned_missing = True
        return False
    sent_all = True
    for part in _chunks(message):
        sent_all = _post(token, chat_id, part, html_mode=True) and sent_all
    return sent_all


if __name__ == "__main__":
    print("sent" if send_telegram("<b>Hi</b> from the day trader") else "not sent (see the log message above)")
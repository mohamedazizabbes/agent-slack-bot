import os
import re
import hashlib
import hmac
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

client = WebClient(token=os.environ["SLACK_BOT_TOKEN"])


def verify_signature(body: bytes, timestamp: str, signature: str) -> bool:
    secret = os.environ["SLACK_SIGNING_SECRET"]
    base = f"v0:{timestamp}:".encode() + body
    expected = "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def format_message(text: str) -> str:
    """Convert LLM markdown output to Slack-friendly format."""
    parts = re.split(r'(```[\w]*\n.*?```)', text, flags=re.DOTALL)
    result = []
    for part in parts:
        if part.startswith("```"):
            inner = re.match(r'```[\w]*\n(.*?)```', part, re.DOTALL)
            if inner:
                code = inner.group(1)
                lines = code.split("\n")
                if lines and re.match(r'^[a-z]+\s*$', lines[0].strip()):
                    lines = lines[1:]
                while lines and not lines[-1].strip():
                    lines.pop()
                result.append("\n".join("    " + line for line in lines))
            else:
                result.append(part)
        else:
            part = re.sub(r'\*\*(.+?)\*\*', r'*\1*', part)
            part = re.sub(r'~~(.+?)~~', r'~\1~', part)
            result.append(part)
    return "".join(result)


def post_message(channel: str, text: str, thread_ts: str | None = None) -> None:
    try:
        text = format_message(text)
        client.chat_postMessage(channel=channel, text=text, thread_ts=thread_ts)
    except SlackApiError as e:
        print(f"Slack API error: {e}")

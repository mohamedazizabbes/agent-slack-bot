import os
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


def post_message(channel: str, text: str, thread_ts: str | None = None) -> None:
    try:
        client.chat_postMessage(channel=channel, text=text, thread_ts=thread_ts)
    except SlackApiError as e:
        print(f"Slack API error: {e}")

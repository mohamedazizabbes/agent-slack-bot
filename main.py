import json
import os
import re
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse

from slack_client import verify_signature, post_message
from rag_client import ask_rag

load_dotenv()

REPOS_FILE = Path(__file__).parent / "repos.json"


def _load_repos() -> dict[str, str]:
    with open(REPOS_FILE) as f:
        return json.load(f)


def _normalize(name: str) -> str:
    return name.lower().removesuffix(".git")


app = FastAPI(title="repo-agent-slack-bot")


@app.get("/")
async def root():
    return {"status": "ok"}


@app.post("/slack/events")
async def slack_events(request: Request):
    body = await request.body()

    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if payload.get("challenge"):
        return PlainTextResponse(payload["challenge"])

    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")

    if not verify_signature(body, timestamp, signature):
        raise HTTPException(status_code=403, detail="Invalid signature")

    event = payload.get("event", {})
    if event.get("type") == "app_mention":
        text = event.get("text", "").strip()
        channel = event["channel"]
        thread_ts = event.get("ts")

        # Strip bot mention (<@U12345>)
        text = re.sub(r"<@\w+>", "", text).strip()

        # Extract /repo_name from anywhere in the message
        m = re.search(r"/(\S+)", text)
        if not m:
            known = ", ".join(f"/{k}" for k in _load_repos())
            msg = f"Usage: @Repo Agent /repo_name your question\nKnown repos: {known}"
            post_message(channel, msg, thread_ts=thread_ts)
            return {"ok": True}

        raw_repo = m.group(1)
        repo_name = _normalize(raw_repo)

        repos = _load_repos()
        entry = repos.get(repo_name)
        if not entry:
            known = ", ".join(f"/{k}" for k in repos)
            post_message(channel, f"Unknown repo /{raw_repo}. Known: {known}", thread_ts=thread_ts)
            return {"ok": True}

        qdrant_name = entry.get("qdrant_name") if isinstance(entry, dict) else entry

        # Remove /repo_name token from text to get the question
        question = re.sub(r"/\S+", "", text, count=1).strip()

        session_id = f"slack:{channel}:{thread_ts or uuid.uuid4().hex}"

        import asyncio

        asyncio.create_task(_handle_query(channel, question, qdrant_name, session_id, thread_ts))

    return {"ok": True}


async def _handle_query(
    channel: str, question: str, target_repo: str, session_id: str, thread_ts: str | None
):
    answer = await ask_rag(question, target_repo, session_id)
    post_message(channel, answer, thread_ts=thread_ts)

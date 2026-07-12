import asyncio
import json
import os
import re
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse

from slack_client import verify_signature, post_message
from rag_client import ask_rag, ingest_repo, ingest_status

load_dotenv()

REPOS_FILE = Path(__file__).parent / "repos.json"


def _load_repos() -> dict[str, str]:
    with open(REPOS_FILE) as f:
        return json.load(f)


def _find_repo(alias: str) -> tuple[str, str] | None:
    """Case-insensitive lookup: returns (original_key, url) or None."""
    repos = _load_repos()
    alias_lower = alias.lower()
    for key, url in repos.items():
        if key.lower() == alias_lower:
            return key, url
    return None


def _normalize(name: str) -> str:
    return name.lower().removesuffix(".git")


def repo_name_from_url(url: str) -> str:
    """Derive the Qdrant repo_name from a GitHub URL.

    Must match rag_backend/repo_manager.py clone_single_repo() exactly.
    """
    name = Path(url.rstrip("/")).name
    if name.endswith(".git"):
        name = name[:-4]
    return name


app = FastAPI(title="repo-agent-slack-bot")

# Channel memory: channel → {"repo_name": ..., "repo_url": ...}
_channel_repos: dict[str, dict] = {}


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

        text = re.sub(r"<@\w+>", "", text).strip()

        m = re.search(r"/(\S+)", text)

        if m:
            raw_repo = m.group(1)
            alias = _normalize(raw_repo)

            found = _find_repo(alias)
            if not found:
                repos = _load_repos()
                known = ", ".join(f"/{k}" for k in repos)
                post_message(channel, f"Unknown repo /{raw_repo}. Known: {known}", thread_ts=thread_ts)
                return {"ok": True}

            _, repo_url = found
            qdrant_name = repo_name_from_url(repo_url)
            question = re.sub(r"/\S+", "", text, count=1).strip()

            # Remember this repo for the channel
            _channel_repos[channel] = {"repo_name": qdrant_name, "repo_url": repo_url}
        else:
            # No /repo_name — check channel memory
            if channel in _channel_repos:
                qdrant_name = _channel_repos[channel]["repo_name"]
                repo_url = _channel_repos[channel]["repo_url"]
                question = text
            else:
                known = ", ".join(f"/{k}" for k in _load_repos())
                msg = f"Usage: @Repo Agent /repo_name your question\nKnown repos: {known}"
                post_message(channel, msg, thread_ts=thread_ts)
                return {"ok": True}

        session_id = f"slack:{channel}:{thread_ts or uuid.uuid4().hex}"

        asyncio.create_task(_answer(channel, question, qdrant_name, repo_url, session_id, thread_ts))

    return {"ok": True}


async def _answer(
    channel: str, question: str, target_repo: str, repo_url: str, session_id: str, thread_ts: str | None
):
    # Ensure repo is indexed before querying
    try:
        status = await ingest_status(target_repo)
    except Exception:
        status = "unknown"

    if status != "ready":
        post_message(channel, f"Indexing `{target_repo}` for the first time — this may take a moment...", thread_ts=thread_ts)
        try:
            ingest_status_result = await ingest_repo(repo_url)
        except Exception:
            ingest_status_result = "error"

        if ingest_status_result == "indexing":
            for _ in range(40):
                await asyncio.sleep(3)
                try:
                    s = await ingest_status(target_repo)
                except Exception:
                    s = "unknown"
                if s == "ready":
                    break
                elif s.startswith("error"):
                    post_message(channel, f"Indexing failed for `{target_repo}`: {s}", thread_ts=thread_ts)
                    return

    answer = await ask_rag(question, target_repo, session_id)
    post_message(channel, answer, thread_ts=thread_ts)

import os
import uuid
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse

from slack_client import verify_signature, post_message
from rag_client import ask_rag

load_dotenv()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    required = ["SLACK_BOT_TOKEN", "SLACK_SIGNING_SECRET", "RAG_BACKEND_URL"]
    missing = [v for v in required if not os.getenv(v)]
    if missing:
        print(f"Missing env vars: {', '.join(missing)}")
    yield


app = FastAPI(lifespan=lifespan, title="repo-agent-slack-bot")


@app.get("/")
async def root():
    return {"status": "ok"}


@app.post("/slack/events")
async def slack_events(request: Request):
    body = await request.body()

    # Slack URL verification — sent without signature headers
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

        # Strip bot mention (<@U12345>) and split
        words = text.split()
        words = [w for w in words if not w.startswith("<@")]
        if len(words) < 2:
            post_message(channel, "Usage: @Repo Agent <repo_name> <question>\nExample: @Repo Agent reservi what is this project?", thread_ts=thread_ts)
            return {"ok": True}

        target_repo = words[0]
        question = " ".join(words[1:])
        session_id = f"slack:{channel}:{thread_ts or uuid.uuid4().hex}"

        import asyncio

        asyncio.create_task(_handle_query(channel, question, target_repo, session_id, thread_ts))

    return {"ok": True}


async def _handle_query(
    channel: str, question: str, target_repo: str, session_id: str, thread_ts: str | None
):
    answer = await ask_rag(question, target_repo, session_id)
    post_message(channel, answer, thread_ts=thread_ts)

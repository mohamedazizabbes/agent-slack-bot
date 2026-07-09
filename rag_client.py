import os
import httpx

RAG_URL = os.environ["RAG_BACKEND_URL"].rstrip("/") + "/query"


async def ask_rag(question: str, target_repo: str, session_id: str) -> str:
    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream(
            "POST",
            RAG_URL,
            json={
                "question": question,
                "target_repo": target_repo,
                "session_id": session_id,
            },
        ) as resp:
            parts: list[str] = []
            buf = ""
            async for chunk in resp.aiter_text():
                buf += chunk
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.strip()
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            return "".join(parts)
                        parts.append(data)
    return "".join(parts)

"""One-time batch ingest all repos from repos.json into Qdrant.

Usage: python batch_ingest.py
"""
import json
import time
import httpx
from pathlib import Path

RAG_BASE = "https://code-explainer-c8g2.onrender.com"
REPOS_FILE = Path(__file__).parent / "repos.json"


def repo_name_from_url(url: str) -> str:
    name = Path(url.rstrip("/")).name
    if name.endswith(".git"):
        name = name[:-4]
    return name


def main():
    repos = json.loads(REPOS_FILE.read_text())
    client = httpx.Client(timeout=120)

    for alias, url in repos.items():
        repo_name = repo_name_from_url(url)

        # Check current status
        try:
            resp = client.get(f"{RAG_BASE}/ingest/status/{repo_name}")
            status = resp.json().get("status", "unknown")
        except Exception:
            status = "unknown"

        if status == "ready":
            print(f"  SKIP  {alias:25s} -> {repo_name:30s} (already indexed)")
            continue

        print(f"  INDEX {alias:25s} -> {repo_name:30s} ...", end=" ", flush=True)

        # Trigger ingest
        try:
            resp = client.post(
                f"{RAG_BASE}/ingest",
                json={"repo_url": url},
            )
            data = resp.json()
            ingest_status = data.get("status", "error")
        except Exception as e:
            print(f"ERROR: {e}")
            continue

        if ingest_status == "indexing":
            # Poll until ready
            for i in range(60):
                time.sleep(3)
                try:
                    resp = client.get(f"{RAG_BASE}/ingest/status/{repo_name}")
                    s = resp.json().get("status", "unknown")
                except Exception:
                    s = "unknown"
                if s == "ready":
                    print("DONE")
                    break
                elif s.startswith("error"):
                    print(f"ERROR: {s}")
                    break
            else:
                print("TIMEOUT (3min)")
        elif ingest_status == "ok":
            print("DONE (sync)")
        else:
            print(f"STATUS: {ingest_status}")

    client.close()
    print("\nDone.")


if __name__ == "__main__":
    main()

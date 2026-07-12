"""Push the approved .sqlx to the Dataform repo via the GitHub contents API.

If GITHUB_TOKEN is empty the step is skipped gracefully — useful during local
development before you create the PAT.
"""
import base64

import requests

from app.config import settings

_API = "https://api.github.com"


def push_file(path: str, content: str, message: str) -> dict:
    """Returns {pushed: bool, sha?: str, url?: str, reason?: str}"""
    if not settings.github_token or not settings.github_repo:
        return {"pushed": False, "reason": "no GITHUB_TOKEN configured — skipping push"}

    headers = {
        "Authorization": f"Bearer {settings.github_token}",
        "Accept": "application/vnd.github+json",
    }
    url = f"{_API}/repos/{settings.github_repo}/contents/{path}"

    # If the file already exists we must send its sha to update it
    sha = None
    existing = requests.get(url, headers=headers, params={"ref": settings.github_branch}, timeout=30)
    if existing.status_code == 200:
        sha = existing.json().get("sha")

    body = {
        "message": message,
        "content": base64.b64encode(content.encode()).decode(),
        "branch": settings.github_branch,
    }
    if sha:
        body["sha"] = sha

    resp = requests.put(url, headers=headers, json=body, timeout=30)
    if resp.status_code not in (200, 201):
        return {"pushed": False, "reason": f"GitHub API {resp.status_code}: {resp.text[:200]}"}
    data = resp.json()
    return {
        "pushed": True,
        "sha": data["commit"]["sha"][:7],
        "url": data["content"]["html_url"],
    }

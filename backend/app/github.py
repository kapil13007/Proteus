"""Publish approved files to the team's Dataform repo: one commit, however many files.

Uses the Git Data API (ref -> commit -> tree -> new commit -> move ref): five
requests total, and the whole table (declaration, params, read/process/write)
lands atomically. The contents API would need one commit per file.
Optional: without GITHUB_TOKEN the step is skipped and the files stay
available as a zip download.
"""
import httpx

from app.config import settings

_API = "https://api.github.com"


def publish(files: list[dict], message: str, transport: httpx.BaseTransport | None = None) -> dict:
    if not settings.github_token or not settings.github_repo:
        return {"pushed": False, "skipped": True,
                "reason": "GITHUB_TOKEN / GITHUB_REPO not set — download the files as a zip instead"}
    repo, branch = settings.github_repo, settings.github_branch
    headers = {"Authorization": f"Bearer {settings.github_token}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    try:
        with httpx.Client(base_url=_API, headers=headers, timeout=30, transport=transport) as gh:
            ref = gh.get(f"/repos/{repo}/git/ref/heads/{branch}")
            ref.raise_for_status()
            parent = ref.json()["object"]["sha"]
            base_tree = gh.get(f"/repos/{repo}/git/commits/{parent}")
            base_tree.raise_for_status()
            tree = gh.post(f"/repos/{repo}/git/trees", json={
                "base_tree": base_tree.json()["tree"]["sha"],
                "tree": [{"path": f["path"], "mode": "100644", "type": "blob", "content": f["content"]}
                         for f in files],
            })
            tree.raise_for_status()
            commit = gh.post(f"/repos/{repo}/git/commits", json={
                "message": message, "tree": tree.json()["sha"], "parents": [parent]})
            commit.raise_for_status()
            sha = commit.json()["sha"]
            gh.patch(f"/repos/{repo}/git/refs/heads/{branch}", json={"sha": sha}).raise_for_status()
    except httpx.HTTPStatusError as e:
        return {"pushed": False, "skipped": False,
                "reason": f"GitHub {e.response.status_code}: {e.response.text[:200]}"}
    except httpx.HTTPError as e:
        return {"pushed": False, "skipped": False, "reason": f"GitHub unreachable: {e}"}
    return {"pushed": True, "skipped": False, "sha": sha[:7], "branch": branch, "files": len(files),
            "url": f"https://github.com/{repo}/commit/{sha}"}

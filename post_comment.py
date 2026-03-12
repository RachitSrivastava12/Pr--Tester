import httpx
import logging
from fetch_diff import generate_jwt

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
PRIVATE_KEY_PATH = "my-pr-detector.private-key.pem"
APP_ID = "3069568"
# ─────────────────────────────────────────────────────────────────────────────


async def get_installation_token(installation_id: int) -> str:
    """Get GitHub installation access token."""
    app_jwt = generate_jwt()
    url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
    headers = {
        "Authorization": f"Bearer {app_jwt}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers)
        response.raise_for_status()
        return response.json()["token"]


def build_comment(pr_data: dict, agent_response: dict) -> str:
    """
    Build the GitHub PR comment body from agent results.
    Matches the format specified in the dev spec.
    """
    status_icon = "✅" if agent_response["failed"] == 0 else "❌"
    passed = agent_response["passed"]
    failed = agent_response["failed"]
    total  = agent_response["total"]

    lines = [
        f"## {status_icon} Traceback QA",
        f"**{passed} passed** · **{failed} failed** · {total} total",
        f"PR #{pr_data['number']} · branch `{pr_data['head_branch']}` · commit `{pr_data.get('head_sha', 'unknown')[:7]}`",
        "",
        "| | Test | Duration | Error |",
        "|---|---|---|---|",
    ]

    for r in agent_response["results"]:
        icon     = "✅" if r["status"] == "passed" else "❌"
        dur      = f"{r['duration_ms'] / 1000:.1f}s"
        error    = r["error"] or "—"
        # Truncate long errors
        if len(error) > 80:
            error = error[:80] + "..."
        lines.append(f"| {icon} | {r['name']} | {dur} | {error} |")

    lines += [
        "",
        "*🤖 These tests were AI-generated from the diff — not human-authored.*",
        "*Tests will not run until accepted in the Traceback dashboard.*",
        "",
        f"[✅ Accept all →](https://traceback.cc/suggestions/accept)",
        f"[View in Traceback →](https://traceback.cc/runs)",
    ]

    return "\n".join(lines)


async def post_pr_comment(pr_data: dict, agent_response: dict) -> dict:
    """
    Post the test results as a comment on the GitHub PR.
    If a comment already exists (pr_comment_id), update it instead of creating a new one.
    """
    installation_id = pr_data["installation_id"]
    repo            = pr_data["repo_name"]
    pr_number       = pr_data["number"]

    token = await get_installation_token(installation_id)
    body  = build_comment(pr_data, agent_response)

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    existing_comment_id = pr_data.get("pr_comment_id")

    async with httpx.AsyncClient() as client:

        if existing_comment_id:
            # ── Update existing comment (no duplicate) ────────────────────
            url = f"https://api.github.com/repos/{repo}/issues/comments/{existing_comment_id}"
            response = await client.patch(url, headers=headers, json={"body": body})
            response.raise_for_status()
            logger.info(f"✏️  Updated existing PR comment #{existing_comment_id}")
            return {"action": "updated", "comment_id": existing_comment_id}

        else:
            # ── Post new comment ──────────────────────────────────────────
            url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
            response = await client.post(url, headers=headers, json={"body": body})
            response.raise_for_status()
            comment_id = response.json()["id"]
            logger.info(f"💬 Posted new PR comment — ID: {comment_id}")
            return {"action": "created", "comment_id": comment_id}
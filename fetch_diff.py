import time
import jwt
import httpx
import logging

logger = logging.getLogger(__name__)

# ── Config — fill these in ────────────────────────────────────────────────────
APP_ID = "3069568"
PRIVATE_KEY_PATH = "my-pr-detector.private-key.pem"        # path to your .pem file
# ─────────────────────────────────────────────────────────────────────────────


def load_private_key() -> str:
    """Read the .pem private key from disk."""
    with open(PRIVATE_KEY_PATH, "r") as f:
        return f.read()


def generate_jwt() -> str:
    """
    Generate a short-lived JWT signed with the GitHub App private key.
    GitHub requires this to authenticate AS the app (valid for 10 mins max).
    """
    private_key = load_private_key()
    now = int(time.time())

    payload = {
        "iat": now - 60,        # issued at (60s in past to allow clock drift)
        "exp": now + (9 * 60),  # expires in 9 minutes
        "iss": APP_ID,          # issuer = your GitHub App ID
    }

    token = jwt.encode(payload, private_key, algorithm="RS256")
    return token


async def get_installation_token(installation_id: int) -> str:
    """
    Exchange the JWT for an Installation Access Token.
    This token lets us call GitHub API on behalf of the installed app.
    """
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
        data = response.json()
        return data["token"]


async def fetch_pr_diff(repo_name: str, pr_number: int, installation_id: int) -> dict:
    """
    Fetch the full diff for a PR — every file changed, lines added/removed.

    Returns a dict with:
      - files: list of changed files with patches
      - raw_diff: the raw unified diff string
      - summary: quick stats per file
    """
    logger.info(f"🔍 Fetching diff for PR #{pr_number} in {repo_name}")

    # Step 1: Get installation access token
    token = await get_installation_token(installation_id)

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient() as client:

        # Step 2: Get list of changed files with patches
        files_url = f"https://api.github.com/repos/{repo_name}/pulls/{pr_number}/files"
        files_response = await client.get(files_url, headers=headers)
        files_response.raise_for_status()
        files_data = files_response.json()

        # Step 3: Get the raw unified diff
        raw_diff_headers = {**headers, "Accept": "application/vnd.github.diff"}
        diff_url = f"https://api.github.com/repos/{repo_name}/pulls/{pr_number}"
        diff_response = await client.get(diff_url, headers=raw_diff_headers)
        diff_response.raise_for_status()
        raw_diff = diff_response.text

    # Step 4: Structure the output
    changed_files = []
    for f in files_data:
        changed_files.append({
            "filename":   f.get("filename"),
            "status":     f.get("status"),        # added / modified / removed
            "additions":  f.get("additions"),
            "deletions":  f.get("deletions"),
            "changes":    f.get("changes"),
            "patch":      f.get("patch", ""),     # the actual line-by-line diff
        })

    result = {
        "repo":        repo_name,
        "pr_number":   pr_number,
        "files":       changed_files,
        "raw_diff":    raw_diff,
        "total_files": len(changed_files),
        "summary": [
            f"{f['status'].upper()} {f['filename']} (+{f['additions']}/-{f['deletions']})"
            for f in changed_files
        ]
    }

    logger.info(f"✅ Diff fetched — {len(changed_files)} files changed")
    for line in result["summary"]:
        logger.info(f"   {line}")

    return result
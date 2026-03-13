import hmac
import hashlib
import json
import logging
from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import JSONResponse
from typing import Optional
from pr_handler import handle_pr_opened
from agent_simulator import router as agent_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Traceback PR Detector", version="2.0.0")
app.include_router(agent_router)

WEBHOOK_SECRET = "mysecret123"

# ── In-memory store for PR run results ───────────────────────────────────────
# key: "{repo}:{pr_number}"  value: full result dict
pr_results_store: dict = {}
# ─────────────────────────────────────────────────────────────────────────────


def verify_signature(payload_body: bytes, signature_header: Optional[str]) -> bool:
    if not signature_header:
        return False
    try:
        sha_name, signature = signature_header.split("=", 1)
    except ValueError:
        return False
    if sha_name != "sha256":
        return False
    mac = hmac.new(WEBHOOK_SECRET.encode(), msg=payload_body, digestmod=hashlib.sha256)
    return hmac.compare_digest(mac.hexdigest(), signature)


@app.get("/")
async def root():
    return {"status": "Traceback PR Detector is running 🚀"}


@app.post("/webhook")
async def github_webhook(
    request: Request,
    x_github_event: Optional[str] = Header(None),
    x_hub_signature_256: Optional[str] = Header(None),
):
    payload_body = await request.body()

    if not verify_signature(payload_body, x_hub_signature_256):
        logger.warning("❌ Invalid webhook signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload = json.loads(payload_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event  = x_github_event
    action = payload.get("action")

    logger.info(f"📩 Received event: {event}, action: {action}")

    if event == "pull_request" and action == "opened":
        pr_data = extract_pr_data(payload)
        logger.info(f"🔔 New PR opened: #{pr_data['number']} — {pr_data['title']}")
        result = await handle_pr_opened(pr_data)

        # ── Store results for web app to fetch ────────────────────────────
        store_key = f"{pr_data['repo_name']}:{pr_data['number']}"
        pr_results_store[store_key] = {
            "pr_number":   pr_data["number"],
            "repo":        pr_data["repo_name"],
            "title":       pr_data["title"],
            "author":      pr_data["author"],
            "pr_url":      pr_data["pr_url"],
            "head_sha":    pr_data.get("head_sha"),
            "head_branch": pr_data["head_branch"],
            "base_branch": pr_data["base_branch"],
            "result":      result,
        }

        return JSONResponse(content={"message": "PR pipeline completed", "result": result})

    return JSONResponse(content={"message": f"Event '{event}' with action '{action}' ignored"})


# ── Web app route — fetch results for a specific PR ───────────────────────────
@app.get("/api/v1/runs/{repo_owner}/{repo_name}/{pr_number}")
async def get_pr_run(repo_owner: str, repo_name: str, pr_number: int):
    """
    Web app calls this to get the test results for a specific PR.
    Returns the same data that was posted as a GitHub PR comment.
    """
    store_key = f"{repo_owner}/{repo_name}:{pr_number}"
    result = pr_results_store.get(store_key)

    if not result:
        raise HTTPException(status_code=404, detail=f"No run found for PR #{pr_number} in {repo_owner}/{repo_name}")

    return JSONResponse(content=result)


# ── Web app route — fetch all PR runs ─────────────────────────────────────────
@app.get("/api/v1/runs")
async def get_all_runs():
    """
    Web app calls this to get all PR runs.
    """
    return JSONResponse(content=list(pr_results_store.values()))


def extract_pr_data(payload: dict) -> dict:
    pr           = payload.get("pull_request", {})
    repo         = payload.get("repository", {})
    installation = payload.get("installation", {})

    return {
        "installation_id": installation.get("id"),
        "number":          pr.get("number"),
        "title":           pr.get("title"),
        "body":            pr.get("body"),
        "state":           pr.get("state"),
        "author":          pr.get("user", {}).get("login"),
        "author_url":      pr.get("user", {}).get("html_url"),
        "pr_url":          pr.get("html_url"),
        "diff_url":        pr.get("diff_url"),
        "patch_url":       pr.get("patch_url"),
        "base_branch":     pr.get("base", {}).get("ref"),
        "head_branch":     pr.get("head", {}).get("ref"),
        "head_sha":        pr.get("head", {}).get("sha"),
        "repo_name":       repo.get("full_name"),
        "repo_url":        repo.get("html_url"),
        "commits":         pr.get("commits"),
        "additions":       pr.get("additions"),
        "deletions":       pr.get("deletions"),
        "changed_files":   pr.get("changed_files"),
        "pr_comment_id":   None,
    }
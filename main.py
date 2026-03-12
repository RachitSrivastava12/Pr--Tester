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


def verify_signature(payload_body: bytes, signature_header: Optional[str]) -> bool:
    """Verify that the webhook came from GitHub using HMAC-SHA256."""
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

    # ── 1. Verify the webhook signature 
    if not verify_signature(payload_body, x_hub_signature_256):
        logger.warning("❌ Invalid webhook signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

    # ── 2. Parse the JSON payload 
    try:
        payload = json.loads(payload_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event  = x_github_event
    action = payload.get("action")

    logger.info(f"📩 Received event: {event}, action: {action}")

    # ── 3. Detect Pull Request opened
    if event == "pull_request" and action == "opened":
        pr_data = extract_pr_data(payload)
        logger.info(f"🔔 New PR opened: #{pr_data['number']} — {pr_data['title']}")
        result = await handle_pr_opened(pr_data)
        return JSONResponse(content={"message": "PR pipeline completed", "result": result})

    # ── 4. Ignore all other events 
    return JSONResponse(content={"message": f"Event '{event}' with action '{action}' ignored"})


def extract_pr_data(payload: dict) -> dict:
    """Extract the useful fields from the PR payload."""
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
        "pr_comment_id":   None,  # will be set after first comment is posted
    }
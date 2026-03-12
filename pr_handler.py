import logging
import httpx
from fetch_diff import fetch_pr_diff
from generate_tests import generate_tests
from post_comment import post_pr_comment

logger = logging.getLogger(__name__)

#just a demo endpoint
AGENT_URL = "http://localhost:8000/api/v1/agent" 


async def handle_pr_opened(pr_data: dict) -> dict:

    logger.info("=" * 60)
    logger.info("🚀 STEP 1 — NEW PULL REQUEST DETECTED")
    logger.info("=" * 60)
    logger.info(f"  Repo        : {pr_data['repo_name']}")
    logger.info(f"  PR #        : {pr_data['number']}")
    logger.info(f"  Title       : {pr_data['title']}")
    logger.info(f"  Author      : {pr_data['author']}")
    logger.info(f"  Base branch : {pr_data['base_branch']}")
    logger.info(f"  Head branch : {pr_data['head_branch']}")
    logger.info(f"  Changes     : +{pr_data['additions']} / -{pr_data['deletions']} in {pr_data['changed_files']} files")
    logger.info(f"  PR URL      : {pr_data['pr_url']}")
    logger.info("=" * 60)

    # ── Step 2: Fetch the diff ────────────────────────────────────────────────
    logger.info("")
    logger.info(" STEP 2 — FETCHING DIFF FROM GITHUB...")
    try:
        diff = await fetch_pr_diff(
            repo_name=pr_data["repo_name"],
            pr_number=pr_data["number"],
            installation_id=pr_data["installation_id"],
        )
        logger.info(f"✅ Diff fetched — {diff['total_files']} files changed:")
        for line in diff["summary"]:
            logger.info(f"   {line}")
    except Exception as e:
        logger.error(f"❌ Failed to fetch diff: {e}")
        return {"status": "error", "step": "fetch_diff", "error": str(e)}

    # ── Step 3: Generate tests with Gemini ────────────────────────────────────
    logger.info("")
    logger.info(" STEP 3 — GENERATING TESTS WITH GEMINI...")
    try:
        test_objects = await generate_tests(diff)
        if not test_objects:
            logger.warning("⚠️ No test goals generated")
            return {"status": "no_tests_generated", "pr_number": pr_data["number"]}
        logger.info(f"✅ {len(test_objects)} test objects generated:")
        for i, t in enumerate(test_objects, 1):
            logger.info(f"   {i}. [{t.get('name')}]")
            logger.info(f"      Goal: {t.get('goal')}")
    except Exception as e:
        logger.error(f"❌ Failed to generate tests: {e}")
        return {"status": "error", "step": "generate_tests", "error": str(e)}

    # ── Step 4: Send to agent ─────────────────────────────────────────────────
    logger.info("")
    logger.info(" STEP 4 — SENDING TESTS TO AGENT...")
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(AGENT_URL, json=test_objects)
            response.raise_for_status()
            agent_response = response.json()
        logger.info(f"✅ Agent completed:")
        logger.info(f"   Passed  : {agent_response['passed']}")
        logger.info(f"   Failed  : {agent_response['failed']}")
        logger.info(f"   Total   : {agent_response['total']}")
        for r in agent_response["results"]:
            icon = "✅" if r["status"] == "passed" else "❌"
            logger.info(f"   {icon} {r['name']} — {r['duration_ms']}ms")
            if r["error"]:
                logger.info(f"      Error: {r['error']}")
    except Exception as e:
        logger.error(f"❌ Agent call failed: {e}")
        return {"status": "error", "step": "agent", "error": str(e)}

    # ── Step 5: Post GitHub PR comment ────────────────────────────────────────
    logger.info("")
    logger.info(" STEP 5 — POSTING RESULTS TO GITHUB PR...")
    try:
        comment_result = await post_pr_comment(pr_data, agent_response)
        logger.info(f"✅ PR comment {comment_result['action']} successfully!")
        logger.info(f"   Comment ID : {comment_result['comment_id']}")
        logger.info(f"   PR URL     : {pr_data['pr_url']}")
    except Exception as e:
        logger.error(f"❌ Failed to post PR comment: {e}")
        return {"status": "error", "step": "post_comment", "error": str(e)}

    logger.info("")
    logger.info("=" * 60)
    logger.info(" PIPELINE COMPLETE!")
    logger.info("=" * 60)

    return {
        "status":           "completed",
        "pr_number":        pr_data["number"],
        "repo":             pr_data["repo_name"],
        "files_changed":    diff["total_files"],
        "tests_generated":  len(test_objects),
        "passed":           agent_response["passed"],
        "failed":           agent_response["failed"],
        "comment_id":       comment_result["comment_id"],
    }
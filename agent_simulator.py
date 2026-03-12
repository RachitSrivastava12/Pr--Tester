import random
import asyncio
import logging
from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/api/v1/agent")
async def simulate_agent(tests: list[dict]):
    """
    Mock agent endpoint — simulates the Traceback agent running tests.
    Returns fake pass/fail results for each test.
    Replace this with the real agent call once Justin merges it to backend.
    """
    logger.info(f"🤖 Agent received {len(tests)} tests to run")

    results = []

    for test in tests:
        # Simulate agent processing time
        await asyncio.sleep(random.uniform(0.5, 2.0))

        # Randomly pass or fail (80% pass rate to simulate real world)
        passed = random.random() > 0.2

        result = {
            "name":         test.get("name"),
            "goal":         test.get("goal"),
            "status":       "passed" if passed else "failed",
            "duration_ms":  random.randint(3000, 15000),
            "error":        None if passed else random.choice([
                "Could not find the expected UI element on the page",
                "Page did not load within the expected time",
                "Assertion failed — expected text not visible",
                "Element was found but interaction failed",
            ]),
        }

        logger.info(f"  {'✅' if passed else '❌'} {test.get('name')} — {result['status']}")
        results.append(result)

    passed_count = sum(1 for r in results if r["status"] == "passed")
    failed_count = len(results) - passed_count

    logger.info(f"🏁 Agent done — {passed_count} passed, {failed_count} failed")

    return {
        "status":   "completed",
        "passed":   passed_count,
        "failed":   failed_count,
        "total":    len(results),
        "results":  results,
    }

import httpx
import json
import logging
import asyncio
import random

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
GEMINI_API_KEY = "AIzaSyCms7kISjK0E8YKGc2b1dqsAKRlgLr_T04"   # 🔁 Replace with your key
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
MAX_DIFF_CHARS = 20000
MAX_RETRIES = 4
# ─────────────────────────────────────────────────────────────────────────────


def build_prompt(diff: dict) -> str:
    files_text = ""
    for f in diff["files"]:
        files_text += f"""
### File: {f['filename']}
Status: {f['status']}
Changes: +{f['additions']} additions / -{f['deletions']} deletions

Diff patch:
{f['patch'] or '(no patch available)'}

"""
    if len(files_text) > MAX_DIFF_CHARS:
        files_text = files_text[:MAX_DIFF_CHARS] + "\n\n[diff truncated — too large]"

    return f"""You are a QA engineer analyzing a code diff from a pull request.

Your job is to look at what changed and generate structured test objects for a browser-based autonomous testing agent.

## Pull Request Info
- Repo: {diff['repo']}
- PR #: {diff['pr_number']}
- Files changed: {diff['total_files']}

## Code Changes
{files_text}

## Your Task
Based on the code changes above, generate a list of test objects.

Each test object must follow this exact JSON structure:
{{
  "name": "short descriptive name for the test",
  "goal": "plain-English description of what user-facing behavior to verify",
  "environments": {{
    "local": "http://localhost:3000",
    "staging": "",
    "production": ""
  }},
  "viewports": {{
    "laptop": true,
    "mobile": false,
    "tablet": false,
    "desktop": true
  }},
  "definition": "AUTONOMOUS"
}}

Rules:
- "name" should be short and specific to the change (e.g. "ImageContainer text visibility")
- "goal" should describe what a real user would experience — not code details
- "environments": always set local to "http://localhost:3000", leave staging and production as empty strings
- "viewports": enable laptop and desktop by default. Enable mobile and tablet only if the diff touches responsive/mobile CSS or layout
- "definition" is always "AUTONOMOUS"
- Generate between 3 to 6 tests — specific to what changed, not generic smoke tests

Return ONLY a valid JSON array of these objects. No explanation, no markdown, no code blocks.

Example:
[
  {{
    "name": "ImageContainer text visibility",
    "goal": "Verify that the text 'the pictures' is visible on the page below the main image",
    "environments": {{"local": "http://localhost:3000", "staging": "", "production": ""}},
    "viewports": {{"laptop": true, "mobile": false, "tablet": false, "desktop": true}},
    "definition": "AUTONOMOUS"
  }}
]

Now generate the test objects for the diff above:"""


async def generate_tests(diff: dict) -> list[dict]:
    logger.info(f"🤖 Generating tests for PR #{diff['pr_number']} — {diff['total_files']} files changed")

    total_patch_size = sum(len(f.get("patch") or "") for f in diff["files"])
    if total_patch_size == 0:
        logger.warning("⚠️  Diff has no patch content — skipping test generation")
        return []

    prompt = build_prompt(diff)

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 4096,
        }
    }

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY,
    }

    raw_response = ""

    for attempt in range(MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(GEMINI_URL, json=payload, headers=headers)

            if response.status_code == 429:
                wait = min(60, (2 ** attempt) * 5) + random.uniform(0, 2)
                logger.warning(f"⚠️ Rate limited — retrying in {wait:.1f}s (attempt {attempt + 1}/{MAX_RETRIES})")
                await asyncio.sleep(wait)
                continue

            response.raise_for_status()
            data = response.json()

            raw_response = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            logger.info(f"📝 Gemini raw response: {raw_response}")

            # Strip markdown fences if Gemini added them
            if "```" in raw_response:
                raw_response = raw_response.split("```")[1]
                if raw_response.startswith("json"):
                    raw_response = raw_response[4:]
            raw_response = raw_response.strip()

            test_objects = json.loads(raw_response)

            if not isinstance(test_objects, list):
                raise ValueError("Gemini response is not a list")

            # Validate each object has required fields
            required_fields = {"name", "goal", "environments", "viewports", "definition"}
            for i, obj in enumerate(test_objects):
                missing = required_fields - set(obj.keys())
                if missing:
                    logger.warning(f"⚠️ Test object {i} missing fields: {missing}")

            logger.info(f"✅ Generated {len(test_objects)} test objects:")
            for i, obj in enumerate(test_objects, 1):
                logger.info(f"   {i}. [{obj.get('name')}] — {obj.get('goal')}")

            return test_objects

        except json.JSONDecodeError as e:
            logger.error(f"❌ Failed to parse Gemini response as JSON: {e}")
            logger.error(f"   Raw response was: {raw_response}")
            return []

        except Exception as e:
            logger.error(f"❌ Gemini API error (attempt {attempt + 1}): {e}")
            if attempt < MAX_RETRIES - 1:
                wait = (2 ** attempt) * 5
                logger.warning(f"   Retrying in {wait}s...")
                await asyncio.sleep(wait)
            else:
                logger.error("❌ All retries exhausted")
                return []

    return []
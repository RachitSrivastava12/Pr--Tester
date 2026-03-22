Workflow : https://mermaid.ai/d/2ed825b1-74d6-4ef8-bcfa-a7df36e48ef8


# PR Detector

Automatically detects when a Pull Request is opened, analyzes the code diff, generates contextual test cases using an LLM, runs them through a test agent, and posts results as a GitHub PR comment.

---

## How It Works

```
PR Opened on GitHub
        │
        ▼
┌─────────────────────┐
│  Step 1 — Detect    │  GitHub App sends webhook → FastAPI receives it
│  main.py            │  Verifies HMAC signature, extracts PR data
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Step 2 — Diff      │  Authenticates with GitHub App private key
│  fetch_diff.py      │  Fetches every changed file + line-by-line patches
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Step 3 — Generate  │  Sends diff to Gemini API
│  generate_tests.py  │  Returns structured test objects for what changed
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Step 4 — Run       │  POSTs test objects to /api/v1/agent
│  agent_simulator.py │  Mock agent — swap with real agent when ready
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Step 5 — Report    │  Posts formatted results as GitHub PR comment
│  post_comment.py    │  Updates existing comment on re-run (no duplicates)
└─────────────────────┘
```

---

## Project Structure

```
pr-detector/
├── main.py               # FastAPI app — webhook receiver & signature verification
├── pr_handler.py         # Orchestrator — runs all 5 steps in order
├── fetch_diff.py         # GitHub API — fetches PR diff using App auth
├── generate_tests.py     # Gemini API — generates structured test objects from diff
├── agent_simulator.py    # Mock agent at POST /api/v1/agent (temporary)
├── post_comment.py       # Posts/updates GitHub PR comment with results
├── requirements.txt      # Python dependencies
├── .env                  # Secrets (never commit this)
└── my-pr-detector.private-key.pem  # GitHub App private key (never commit this)
```

---

## Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Create `.env` file
```env
GITHUB_APP_ID=your-app-id
GITHUB_WEBHOOK_SECRET=your-webhook-secret
GITHUB_PRIVATE_KEY_PATH=my-pr-detector.private-key.pem
GEMINI_API_KEY=your-gemini-api-key
```

### 3. Run the server
```bash
uvicorn main:app --reload
```

### 4. Expose locally with ngrok (for development)
```bash
ngrok http 8000
```
Copy the ngrok URL → paste as Webhook URL in GitHub App settings.

---

## GitHub App Configuration

1. Go to **GitHub → Settings → Developer Settings → GitHub Apps**
2. Set **Webhook URL** → `https://your-ngrok-url.ngrok-free.app/webhook`
3. Set **Webhook Secret** → same value as `GITHUB_WEBHOOK_SECRET` in `.env`
4. Under **Permissions** → Repository permissions → Pull requests → `Read & Write`
5. Under **Subscribe to events** → check `Pull requests`
6. **Install the app** on your target repo — you can choose all repos or specific ones

---

## Test Object Format

Each generated test follows this schema:

```json
{
  "name": "Search Input and Result Display",
  "goal": "Verify that entering a valid query into the search bar displays correct results",
  "environments": {
    "local": "http://localhost:3000",
    "staging": "",
    "production": ""
  },
  "viewports": {
    "laptop": true,
    "mobile": false,
    "tablet": false,
    "desktop": true
  },
  "definition": "AUTONOMOUS"
}
```

---

## GitHub PR Comment Output

When the pipeline completes, a comment is automatically posted on the PR:

```
## ✅ PR Detector QA
4 passed · 1 failed · 5 total
PR #3 · branch `main` · commit `a3f92c1`

|   | Test                          | Duration | Error                              |
|---|-------------------------------|----------|------------------------------------|
| ✅ | Search Input and Result Display | 8.1s   | —                                  |
| ✅ | Network Switch and Data Update  | 6.4s   | —                                  |
| ✅ | Main Dashboard Layout           | 9.7s   | —                                  |
| ✅ | Wallet Connect/Disconnect       | 7.3s   | —                                  |
| ❌ | Transaction Detail Modal        | 11.7s  | Could not find expected UI element |

🤖 These tests were AI-generated from the diff — not human-authored.
```

---

## API Routes

| Method | Route | Description |
|--------|-------|-------------|
| `POST` | `/webhook` | Receives GitHub webhook events |
| `POST` | `/api/v1/agent` | Mock agent endpoint |
| `GET` | `/api/v1/runs` | Get all PR run results |
| `GET` | `/api/v1/runs/{owner}/{repo}/{pr_number}` | Get results for a specific PR |

---

## Swapping Mock Agent with Real Agent

When the real agent is ready, update one line in `pr_handler.py`:

```python
# Current (mock)
AGENT_URL = "http://localhost:8000/api/v1/agent"

# Replace with real agent URL
AGENT_URL = "http://localhost:REAL_PORT/api/v1/agent"
```

Then `agent_simulator.py` can be removed.

---

## Authentication Flow

```
.pem private key
      ↓
Generate JWT (valid 9 mins)
      ↓
POST /app/installations/{installation_id}/access_tokens
      ↓
Short-lived installation token
      ↓
Call GitHub API with that token
```

- **JWT** proves we are the GitHub App
- **installation_id** (from webhook payload) identifies which user's repo
- **Installation token** gives scoped access to only that repo

---

## Tech Stack

- **FastAPI** — webhook server
- **PyJWT** — GitHub App JWT generation
- **httpx** — async HTTP calls to GitHub & Gemini APIs
- **Gemini 2.0 Flash** — LLM for test generation
- **GitHub App** — webhook events & API authentication
- **python-dotenv** — environment variable management

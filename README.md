# Autonomous AI Testing Agent 🤖

An **AI-powered QA coworker** that integrates directly into your GitHub CI/CD pipeline. When a Pull Request is opened, this agent automatically:

1. 🔍 **Inspects** the live target application's DOM to find real element selectors
2. 📋 **Reads** the PR description to understand what changed
3. ✍️ **Generates** Playwright/Pytest test scripts using actual selectors (no guessing)
4. ▶️ **Executes** the tests in a Docker sandbox
5. 🔄 **Self-heals** if the scripts error (up to 3 retries, without weakening assertions)
6. 💬 **Posts** a formatted test results comment directly on the PR

---

## Architecture

```
PR Opened → GitHub Actions → Docker Container
                                    │
                            ┌───────▼────────┐
                            │  inspect_page  │ ← Playwright scrapes live DOM
                            └───────┬────────┘
                            ┌───────▼────────────────┐
                            │  analyze_requirements  │ ← LLM reads PR + DOM
                            └───────┬────────────────┘
                            ┌───────▼────────┐
                            │ generate_tests │ ← LLM writes Pytest script
                            └───────┬────────┘
                            ┌───────▼────────┐
                            │ execute_tests  │ ← Pytest + Playwright runs
                            └───────┬────────┘
                          pass? ◄───┘──► fail & retries < 3?
                            │                     │
                            └──────┬──────────────┘
                            ┌──────▼───────┐
                            │report_results│ ← PyGithub posts PR comment
                            └──────────────┘
```

**Tech Stack:** Python · LangGraph (ReAct) · LangChain-Groq (Llama 3 70B) · Playwright · Pytest · Docker · GitHub Actions · PyGithub

---

## Quick Start (Local Development)

### Prerequisites

- Python 3.10+
- Node.js (for `npx serve`, optional)
- A Groq API key (free at [console.groq.com](https://console.groq.com))

### 1. Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Set environment variables

```bash
# Create a .env file (already gitignored)
echo "GROQ_API_KEY=your_groq_api_key_here" > .env
```

### 3. Start the target demo app

```bash
# In one terminal:
python -m http.server 8080 --directory app
```

### 4. Run the agent

```bash
# In another terminal:
python src/agent.py
```

**Expected output:**

```
[Agent] Starting in Local Dev Mode
[Agent] Step 1/4 — Inspecting live page at http://localhost:8080 ...
--- DOM INSPECTION REPORT ---
Page Title: Simple Target Application
Form Fields:
  <input type="email" id="email" ...> [REQUIRED]
  <input type="text" id="cardNumber" ...> [REQUIRED]
Buttons:
  <button id="submitOrderBtn">: "Submit Order"
Feedback / Message Elements:
  id="successMsg": "Order processed successfully!"
  id="errorMsg": "Please fill out all fields."
--- END DOM INSPECTION REPORT ---

[Agent] Step 2/4 — Analyzing PR requirements ...
[Agent] Step 3/4 — Generating test script (Attempt 1) ...
[Agent] Step 4/4 — Executing test script (Attempt 1) ...
...
```

---

## CI/CD Setup (GitHub Actions)

### 1. Add your Groq API key as a secret

Go to your repo → **Settings → Secrets and variables → Actions → New repository secret**

- Name: `GROQ_API_KEY`
- Value: your Groq API key

> **Note:** `GITHUB_TOKEN` is automatically provided by GitHub Actions — no setup needed.

### 2. The workflow triggers automatically

Every time a PR is opened or updated, the `ai-qa` job runs and posts a comment like:

---

> **🤖 Autonomous AI Testing Agent Report**
>
> **Status: ✅ PASSED** | Attempts: 1
>
> | Metric       | Value                   |
> | ------------ | ----------------------- |
> | Target URL   | `http://localhost:8080` |
> | Tests Passed | ✅ 5                    |
> | Tests Failed | —                       |

---

### 3. View the HTML Report

After each run, the full test report is uploaded as a GitHub Actions artifact named **`ai-test-report`** and retained for 14 days.

---

## Project Structure

```
ai-testing-agent/
├── .github/
│   └── workflows/
│       └── ai-qa.yml           # GitHub Actions CI workflow
├── app/
│   └── index.html              # Demo target application (checkout form)
├── artifact-results/           # Sample outputs from a real CI run
│   ├── test_generated.py       # Example generated test script
│   ├── report.html             # Example HTML test report
│   ├── conftest.py             # Pytest report customization
│   └── pytest.ini              # Pytest configuration
├── src/
│   ├── agent.py                # Main LangGraph agent (4 nodes + routing)
│   └── tools/
│       └── page_inspector.py   # Playwright DOM scraper tool
├── Dockerfile                  # Agent container definition
├── requirements.txt            # Python dependencies
└── README.md
```

---

## How the Agent Self-Heals (and Why It's Trustworthy)

The agent distinguishes between two types of failures:

| Failure Type                                                    | Agent Action                                                    |
| --------------------------------------------------------------- | --------------------------------------------------------------- |
| **Python/API Error** (e.g. wrong method name, `AttributeError`) | Fixes the code, keeps all assertions                            |
| **Assertion Failure** (test ran, app behavior wrong)            | Keeps the assertion — marks the **app** as broken, NOT the test |

This means the agent will never "cheat" by lowering expectations to make tests pass. If the application has a real bug, the agent will report a failure.

---

## Environment Variables

| Variable            | Required  | Description                                      |
| ------------------- | --------- | ------------------------------------------------ |
| `GROQ_API_KEY`      | ✅ Always | Groq LLM API key                                 |
| `GITHUB_TOKEN`      | CI only   | Auto-provided by GitHub Actions                  |
| `GITHUB_REPOSITORY` | CI only   | Auto-provided (`owner/repo`)                     |
| `WORKSPACE_DIR`     | CI only   | Directory for test artifacts (default: temp dir) |

# Autonomous AI Testing Agent 🤖🧪

An autonomous, LLM-powered "digital coworker" that integrates directly into your CI/CD pipeline to dynamically generate, execute, and self-heal end-to-end (E2E) UI tests on every Pull Request.

## 🌟 The Problem it Solves

QA engineers currently spend a disproportionate amount of time updating brittle E2E tests (e.g., when a UI selector changes due to a refactor) rather than designing edge-case exploratory tests.

This agent shifts quality assurance completely left. By catching regressions at the Pull Request stage automatically, and actively _repairing_ broken test scripts when UI elements change, the cost of maintaining test coverage drops exponentially.

## 🚀 Key Features

- **Requirements Analyst:** Reads the PR diff and description to understand exactly what needs to be tested.
- **Dynamic Script Generation:** Uses **Llama 3 (via Groq)** to write a Python Playwright/Pytest script tailored to the PR's changes.
- **Self-Healing Execution:** Executes the generated tests in an isolated Docker sandbox. If a test fails due to a changed DOM selector, it analyzes the stack trace and attempts to rewrite and fix the script autonomously.
- **CI/CD Native:** Runs fully within **GitHub Actions** (`.github/workflows/ai-qa.yml`), requiring no external infrastructure.
- **100% Free / Open Source Stack:** Built with LangGraph, Playwright, Pytest, and the Groq API (generous free tier).

## 🛠️ Architecture & Tech Stack

- **Orchestration:** [LangGraph](https://python.langchain.com/docs/langgraph) (Provides fine-grained state control for cyclic retry/healing loops).
- **LLM Engine:** Llama 3 70B via the [Groq API](https://console.groq.com/).
- **Testing Framework:** Playwright for Python + Pytest.
- **Environment:** Ephemeral Docker Containers (`mcr.microsoft.com/playwright/python`).

## ⚙️ How it Works in CI/CD

1. A developer opens a Pull Request on GitHub.
2. The GitHub Action workflow is triggered.
3. The Target Application is spun up locally in the GitHub runner.
4. The Agent Docker container runs, passing the PR details and Target URL to the LangGraph brain.
5. The LLM generates the Pytest script, runs it via Playwright, and iterates if necessary.
6. The test results (and any bug findings) are reported.

## 💻 Local Setup (For Development)

1. Clone the repository.
   ```bash
   git clone https://github.com/your-username/ai-testing-agent.git
   ```
2. Set up the virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: .\venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```
4. Add your API key to a `.env` file:
   ```env
   GROQ_API_KEY=gsk_your_key_here
   ```
5. Run the agent locally:
   ```bash
   python src/agent.py
   ```

## 📝 Future Roadmap

- [ ] Connect `PyGithub` to post Execution Reports directly as PR Comments.
- [ ] Add Visual Regression Support (Screenshot Diffing).
- [ ] Support complex multi-step authentication flows.

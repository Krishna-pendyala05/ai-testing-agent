"""
Autonomous AI Testing Agent
----------------------------
A LangGraph-powered ReAct agent that:
  1. Inspects a live target URL to extract real DOM selectors
  2. Reads a PR description to understand what changed
  3. Generates Playwright/Pytest test scripts using REAL selectors
  4. Executes the tests inside the current environment
  5. Self-heals on execution errors (up to 3 retries)
  6. Posts a formatted results comment back to the GitHub PR

Usage (CI/CD mode):
    python src/agent.py <PR_NUMBER> "<PR_BODY>" "<TARGET_URL>"

Usage (local dev mode — no args needed):
    python src/agent.py
"""

import os
import re
import sys
import tempfile
import subprocess
import textwrap
from typing import TypedDict
from langgraph.graph import StateGraph, END
from langchain_groq import ChatGroq
from langchain_community.chat_models import ChatOllama
from langchain_core.messages import HumanMessage
from dotenv import load_dotenv

# Local tools
sys.path.insert(0, os.path.dirname(__file__))
from tools.page_inspector import inspect_page
from tools.report_generator import generate_html_report

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY")  # e.g. "owner/repo"

# Ollama fallback config (override via env vars if needed)
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL", "llama3")

if not GROQ_API_KEY:
    print("WARNING: GROQ_API_KEY is not set. Ensure it is passed via environment variables in CI/CD.")

# ---------------------------------------------------------------------------
# Agent State
# ---------------------------------------------------------------------------
class AgentState(TypedDict):
    pr_number: str
    pr_description: str
    target_url: str
    page_context: str        # Real DOM structure from the live page
    test_requirements: str   # LLM-generated test plan
    generated_test_code: str # LLM-generated Pytest/Playwright script
    execution_logs: str      # Raw stdout/stderr from pytest
    execution_status: str    # "pending" | "success" | "failed"
    attempt_number: int      # 1-indexed attempt count (starts at 1 for first run)

# ---------------------------------------------------------------------------
# LLM  —  Groq primary, Ollama fallback on rate-limit
# ---------------------------------------------------------------------------
llm = ChatGroq(
    temperature=0,
    model_name="llama-3.3-70b-versatile",
    groq_api_key=GROQ_API_KEY,
    request_timeout=60,
)

llm_fallback = ChatOllama(
    base_url=OLLAMA_BASE_URL,
    model=OLLAMA_MODEL,
    temperature=0,
)


def invoke_llm(messages: list) -> object:
    """
    Try Groq first.  If a rate-limit (429 / RateLimitError) is returned,
    automatically fall back to the local Ollama instance.
    Any other exception is re-raised so the caller can surface it.
    """
    try:
        return llm.invoke(messages)
    except Exception as exc:
        exc_str = str(exc).lower()
        # Groq surfaces rate limits as status 429 or the word 'rate_limit'
        if "429" in exc_str or "rate_limit" in exc_str or "rate limit" in exc_str:
            print(
                f"[Agent] ⚠️  Groq rate limit hit — switching to Ollama "
                f"({OLLAMA_MODEL} @ {OLLAMA_BASE_URL}) ..."
            )
            return llm_fallback.invoke(messages)
        raise

# ---------------------------------------------------------------------------
# Node 1: Page Inspector  (THE FIX — agent now SEES the real app)
# ---------------------------------------------------------------------------
def node_inspect_page(state: AgentState) -> dict:
    """
    Visit the target URL using headless Playwright and extract all interactive
    elements. This gives the LLM real IDs/selectors so it never has to guess.
    """
    print(f"\n[Agent] Step 1/4 — Inspecting live page at {state['target_url']} ...")
    context = inspect_page(state["target_url"])
    print(context)
    return {"page_context": context}


# ---------------------------------------------------------------------------
# Node 2: Requirements Analyst
# ---------------------------------------------------------------------------
def node_analyze_requirements(state: AgentState) -> dict:
    """
    Use the PR description + actual page DOM to determine exactly what to test.
    """
    print("\n[Agent] Step 2/4 — Analyzing PR requirements ...")
    prompt = textwrap.dedent(f"""
        You are a senior QA Test Analyst reviewing a Pull Request.

        ## Pull Request Description
        {state['pr_description']}

        ## Live Application DOM (actual elements on the page right now)
        {state['page_context']}

        ## Your Task
        Based on the PR description and the REAL elements on the page above,
        list specific, actionable test cases. For each test case include:
          - What to test (user scenario)
          - Which elements to interact with (use the EXACT IDs from the DOM above)
          - The expected outcome

        Be precise. Only test things relevant to the PR.
    """).strip()

    response = invoke_llm([HumanMessage(content=prompt)])
    print("[Agent] Requirements analysis complete.")
    return {"test_requirements": response.content}


# ---------------------------------------------------------------------------
# Node 3: Test Generator (with self-heal awareness)
# ---------------------------------------------------------------------------
def node_generate_tests(state: AgentState) -> dict:
    """
    Generate a runnable Pytest/Playwright script using real DOM selectors.
    On retry attempts, feed back failure logs and explicitly forbid weakening assertions.
    """
    attempt = state.get("attempt_number", 1)
    print(f"\n[Agent] Step 3/4 — Generating test script (Attempt {attempt}) ...")

    base_prompt = textwrap.dedent(f"""
        You are an expert SDET (Software Development Engineer in Test).

        ## Test Requirements
        {state.get('test_requirements', '')}

        ## Live Application DOM
        {state.get('page_context', '')}

        ## Target URL
        {state['target_url']}

        ## Instructions (FOLLOW EXACTLY)
        1. Output ONLY valid, executable Python code — NO markdown fences, NO explanations.
        2. Start with: `import pytest` and `from playwright.sync_api import sync_playwright`
        3. Use the `@pytest.fixture` pattern for page setup (synchronous Playwright, headless=True).
        4. Every test function MUST start with `test_`.
        5. Use ONLY the element IDs and selectors found in the Live Application DOM above.
           DO NOT invent or guess any selector that is not listed there.
        6. For visibility checks, use Playwright's `page.locator("#id").is_visible()` (not `query_selector(...).is_visible()`).
        7. Each test function MUST have a docstring in EXACTLY this format:
           \"\"\"
           INTENT: one sentence describing the behavior being verified.
           EXPECTED: the specific outcome (element text, visibility, URL, etc.).
           \"\"\"
        8. Set a default timeout of 5000ms on the page fixture.
    """).strip()

    # -----------------------------------------------------------------------
    # Self-heal context: distinguish execution errors vs assertion failures
    # -----------------------------------------------------------------------
    if attempt > 1 and state.get("execution_logs"):
        logs = state["execution_logs"]

        # Check whether the previous failure was a Python/API error or a real assertion failure
        has_attribute_error = "AttributeError" in logs or "ImportError" in logs or "SyntaxError" in logs
        has_assertion_failure = "AssertionError" in logs or "assert False" in logs

        if has_attribute_error and not has_assertion_failure:
            # Pure technical failure — just fix the Python code
            heal_context = textwrap.dedent(f"""

                ## Previous Attempt Failed — Technical Errors Only
                The previous script had Python/API errors (not assertion failures).
                Fix ONLY the code errors listed below. Do NOT change any assertions.

                ERRORS:
                {logs}
            """).strip()
        elif has_assertion_failure:
            # The tests ran but caught real failures — do NOT lower the bar
            heal_context = textwrap.dedent(f"""

                ## Previous Attempt — Assertion Failures Detected
                Some tests FAILED because the application behavior did not match expectations.
                This may indicate real bugs in the application.

                CRITICAL RULE: Do NOT weaken or remove failing assertions to make tests pass.
                If the application is broken, keep the assertion and add a comment explaining
                the expected vs actual behavior. You may use `pytest.mark.xfail(strict=True)`
                only if the behavior is a known limitation documented in the PR.

                Fix only genuine Python syntax or API usage errors.

                LOGS:
                {logs}
            """).strip()
        else:
            heal_context = f"\n\n## Previous Run Logs\n{logs}"

        base_prompt += "\n\n" + heal_context

    response = invoke_llm([HumanMessage(content=base_prompt)])

    # Robustly extract the first fenced code block the LLM may have wrapped
    code = response.content.strip()
    match = re.search(r"```(?:python)?\n(.*?)```", code, re.DOTALL)
    if match:
        code = match.group(1).strip()
    else:
        # Fallback: strip any stray fence markers globally
        code = re.sub(r"```(?:python)?", "", code).strip()

    return {"generated_test_code": code}


# ---------------------------------------------------------------------------
# Node 4: Test Executor
# ---------------------------------------------------------------------------
CONFTEST_CONTENT = textwrap.dedent("""
    import pytest

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(item, call):
        outcome = yield
        report = outcome.get_result()
        report.description = str(item.function.__doc__) if item.function.__doc__ else 'N/A'
""").strip()


def node_execute_tests(state: AgentState) -> dict:
    """
    Write the generated code to a temp directory (alongside conftest.py),
    execute pytest, capture logs, and return status + incremented attempt count.
    """
    code = state["generated_test_code"]
    attempt = state.get("attempt_number", 1)

    # Determine report output path
    workspace = os.environ.get("WORKSPACE_DIR", tempfile.mkdtemp())
    os.makedirs(workspace, exist_ok=True)

    test_file = os.path.join(workspace, "test_generated.py")
    conftest_file = os.path.join(workspace, "conftest.py")
    report_file = os.path.join(workspace, "report.html")

    print(f"\n[Agent] Step 4/4 — Executing test script (Attempt {attempt}) ...")
    print(f"--- GENERATED TEST CODE (saved to {test_file}) ---")
    print(code)
    print("---")

    with open(test_file, "w") as f:
        f.write(code)
    with open(conftest_file, "w") as f:
        f.write(CONFTEST_CONTENT)

    result = subprocess.run(
        ["pytest", test_file, "-v", "--tb=short"],
        capture_output=True,
        text=True,
        cwd=workspace,
    )

    status = "success" if result.returncode == 0 else "failed"
    logs = result.stdout + "\n" + result.stderr

    print(f"--- PYTEST LOGS ---\n{logs}---")
    print(f"[Agent] Execution finished. Status: {status.upper()}")
    if status == "failed":
        print("[Agent] Errors detected. Preparing to self-heal...")

    # Generate custom modern HTML report
    try:
        generate_html_report(
            logs=logs,
            output_path=report_file,
            test_code=code,
            target_url=state.get("target_url", ""),
            pr_number=state.get("pr_number", ""),
            github_repo=GITHUB_REPOSITORY or "",
        )
    except Exception as rg_err:
        print(f"[Agent] ⚠️  Report generation failed (non-fatal): {rg_err}")

    return {
        "execution_status": status,
        "execution_logs": logs,
        "attempt_number": attempt + 1,
    }


# ---------------------------------------------------------------------------
# Node 5: Report Results to GitHub PR
# ---------------------------------------------------------------------------
def node_report_results(state: AgentState) -> dict:
    """
    Post a formatted Markdown comment to the GitHub PR with the test summary.
    Requires GITHUB_TOKEN, GITHUB_REPOSITORY, and pr_number in state.
    """
    if not GITHUB_TOKEN or not GITHUB_REPOSITORY:
        print("\n[Agent] Skipping PR comment — GITHUB_TOKEN or GITHUB_REPOSITORY not set.")
        _print_summary(state)
        return {}

    pr_number_raw = state.get("pr_number", "")
    if not pr_number_raw:
        print("\n[Agent] Skipping PR comment — pr_number not provided.")
        return {}

    try:
        pr_num = int(pr_number_raw)
    except ValueError:
        print(f"\n[Agent] Skipping PR comment — invalid pr_number: {pr_number_raw}")
        return {}

    status = state.get("execution_status", "unknown")
    logs = state.get("execution_logs", "")
    total_attempts = state.get("attempt_number", 1) - 1  # attempts completed

    # Parse test counts from pytest final summary line (robust regex)
    passed_match = re.search(r"(\d+) passed", logs)
    failed_match = re.search(r"(\d+) failed", logs)
    passed = int(passed_match.group(1)) if passed_match else 0
    failed = int(failed_match.group(1)) if failed_match else 0

    # Per-test results table for PR comment
    test_rows = []
    for m in re.finditer(
        r'^(PASSED|FAILED|ERROR|SKIPPED)\s+[\w./\\-]+\.py::(test_\w+)',
        logs, re.MULTILINE
    ):
        icon = "✅" if m.group(1) == "PASSED" else "❌"
        pretty = m.group(2).removeprefix("test_").replace("_", " ").title()
        test_rows.append(f"| {pretty} | {icon} {m.group(1)} |")
    
    # Check if we successfully parsed the tests table
    if test_rows:
        tests_table = "| Test | Result |\n|---|---|\n" + "\n".join(test_rows)
    else:
        tests_table = "_No test results parsed._"

    badge = "✅ PASSED" if status == "success" else "❌ FAILED"
    workspace = os.environ.get("WORKSPACE_DIR", "")
    comment_body = textwrap.dedent(f"""
        ## 🤖 Autonomous AI Testing Agent Report

        **PR #{pr_num}** | **Status: {badge}** | **Attempts: {total_attempts}**

        | Metric | Value |
        |--------|-------|
        | Target URL | `{state.get("target_url", "N/A")}` |
        | Tests Passed | ✅ {passed} |
        | Tests Failed | {"❌ " + str(failed) if failed > 0 else "—"} |
        | Total Attempts | {total_attempts} |

        ### 📊 Per-Test Results

        {tests_table}

        > 📄 A detailed HTML report has been saved to `artifact-generated-for-test-PR/`
        > in this repository for full visual inspection.

        <details>
        <summary>📋 Full Test Logs (click to expand)</summary>

        ```
        {logs[-3000:]}
        ```

        </details>

        ---
        *Generated by [Autonomous AI Testing Agent](https://github.com/{GITHUB_REPOSITORY})*
    """).strip()

    try:
        from github import Github
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPOSITORY)
        pr = repo.get_pull(pr_num)
        pr.create_issue_comment(comment_body)
        print(f"\n[Agent] ✅ Posted test results comment to PR #{pr_num}")
    except Exception as e:
        print(f"\n[Agent] ⚠️  Could not post GitHub comment: {e}")
        _print_summary(state)
        print("--- PR COMMENT BODY ---")
        print(comment_body)
        print("---")

    return {}


def _print_summary(state: AgentState):
    """Print a local summary when not posting to GitHub."""
    status = state.get("execution_status", "unknown")
    badge = "✅ PASSED" if status == "success" else "❌ FAILED"
    print(f"\n{'='*60}")
    print(f"  AUTONOMOUS AI TESTING AGENT — FINAL RESULT: {badge}")
    print(f"  Target: {state.get('target_url', 'N/A')}")
    print(f"  Attempts: {state.get('attempt_number', 1) - 1}")
    print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# Routing Logic
# ---------------------------------------------------------------------------
def should_continue(state: AgentState) -> str:
    """
    After execution:
      - SUCCESS → move to report_results
      - FAILED and attempts < 4 (i.e., up to 3 retries) → regenerate
      - FAILED and max retries hit → move to report_results anyway
    """
    status = state.get("execution_status", "pending")
    attempts_completed = state.get("attempt_number", 2) - 1  # attempt_number was already incremented

    if status == "success":
        print("[Agent] All tests passed! Moving to report results.")
        return "report_results"

    # attempts_completed: 1 = first run done, 2 = first retry done, etc.
    if attempts_completed < 4:  # allow up to 3 retries (4 total runs)
        print(f"[Agent] Retrying... ({attempts_completed} attempt(s) done, max 4 total)")
        return "generate_tests"

    print("[Agent] Maximum retries reached (3 retries / 4 total attempts). Reporting results.")
    return "report_results"


# ---------------------------------------------------------------------------
# Graph Assembly
# ---------------------------------------------------------------------------
def create_agent():
    workflow = StateGraph(AgentState)

    workflow.add_node("inspect_page", node_inspect_page)
    workflow.add_node("analyze_requirements", node_analyze_requirements)
    workflow.add_node("generate_tests", node_generate_tests)
    workflow.add_node("execute_tests", node_execute_tests)
    workflow.add_node("report_results", node_report_results)

    # Linear flow
    workflow.set_entry_point("inspect_page")
    workflow.add_edge("inspect_page", "analyze_requirements")
    workflow.add_edge("analyze_requirements", "generate_tests")
    workflow.add_edge("generate_tests", "execute_tests")

    # Conditional: retry or report
    workflow.add_conditional_edges(
        "execute_tests",
        should_continue,
        {
            "generate_tests": "generate_tests",
            "report_results": "report_results",
        }
    )

    workflow.add_edge("report_results", END)

    return workflow.compile()


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent = create_agent()

    if len(sys.argv) > 3:
        # CI/CD mode: python src/agent.py <PR_NUMBER> "<PR_BODY>" "<TARGET_URL>"
        pr_number = sys.argv[1]
        pr_body = sys.argv[2]
        target_url = sys.argv[3]
        pr_description = f"PR #{pr_number}: {pr_body}"
        print(f"[Agent] Starting in CI/CD Mode — target: {target_url}")
    else:
        # Local dev mode
        pr_number = "0"
        pr_description = (
            "Added a new 'Submit Order' button on the checkout page. "
            "Refactored form validation to also validate email format."
        )
        target_url = "http://localhost:8080"
        print("[Agent] Starting in Local Dev Mode")

    initial_state: AgentState = {
        "pr_number": pr_number,
        "pr_description": pr_description,
        "target_url": target_url,
        "page_context": "",
        "test_requirements": "",
        "generated_test_code": "",
        "execution_logs": "",
        "execution_status": "pending",
        "attempt_number": 1,
    }

    print("\n--- Autonomous AI Testing Agent Starting ---\n")
    for event in agent.stream(initial_state):
        pass  # Nodes print their own status updates

    print("\n--- Agent Run Complete ---")

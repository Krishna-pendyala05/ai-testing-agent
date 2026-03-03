import os
from typing import TypedDict, Annotated, Sequence
import operator
from langgraph.graph import StateGraph, END
from langchain_groq import ChatGroq
from langchain_core.messages import BaseMessage, HumanMessage
from dotenv import load_dotenv

# Load environment variables (API Key)
load_dotenv()
api_key = os.getenv("GROQ_API_KEY")

if not api_key:
    print("Warning: GROQ_API_KEY is not set globally. Ensure it is passed via environment variables in CI/CD.")

# Define the State our Agent will carry through the graph
class AgentState(TypedDict):
    pr_description: str
    target_url: str
    test_requirements: str
    generated_test_code: str
    execution_logs: str
    execution_status: str # "success", "failed", "pending"
    retry_count: int
    messages: Annotated[Sequence[BaseMessage], operator.add]

# Initialize the LLM (using Groq's Llama 3 70B for strong reasoning)
llm = ChatGroq(temperature=0, model_name="llama-3.3-70b-versatile", groq_api_key=api_key)

# ---------------------------------------------------------
# Node 1: Requirements Analyst
# ---------------------------------------------------------
def analyze_requirements(state: AgentState):
    print("Agent: Analyzing PR requirements...")
    prompt = f"""You are an expert QA Test Analyst.
    Read the following Pull Request description and determine the exact testing requirements.
    What needs to be tested on the target URL ({state['target_url']})?
    Write out specific, actionable test cases.
    
    PR Description:
    {state['pr_description']}
    """
    response = llm.invoke([HumanMessage(content=prompt)])
    return {"test_requirements": response.content}

# ---------------------------------------------------------
# Node 2: QA Automation Engineer (Test Generator)
# ---------------------------------------------------------
def generate_tests(state: AgentState):
    print(f"Agent: Generating Python/Playwright test script (Attempt {state.get('retry_count', 0) + 1})...")
    
    # Try to fetch the HTML of the target app to give the LLM context
    import urllib.request
    try:
        req = urllib.request.urlopen(state['target_url'])
        html_context = req.read().decode('utf-8')
    except Exception as e:
        html_context = f"Could not fetch HTML: {e}"
        
    prompt = f"""You are an expert SDET (Software Development Engineer in Test).
    Write a complete Python Playwright script using Pytest to test these requirements:
    {state.get('test_requirements', '')}
    
    The target URL is: {state['target_url']}
    
    Here is the DOM/HTML of the target page to help you write accurate selectors. Do not hallucinate fields that do not exist in this HTML:
    ```html
    {html_context}
    ```
    
    CRITICAL INSTRUCTIONS:
    1. Output ONLY valid, runnable Python code. NO markdown formatting, NO explanations.
    2. Start the script with imports (import pytest, from playwright.sync_api import sync_playwright).
    3. Use synchronous Playwright. 
    4. Write tests as functions starting with `test_` for Pytest to discover them.
    5. Ensure the test uses headless mode.
    6. Set a very short timeout for page actions, e.g. `page.set_default_timeout(3000)` so tests fail fast if selectors are wrong.
    7. ABSOLUTELY DO NOT explicitly comment out test assertions or actions. Do not write "Since the provided HTML does not contain...". Write the actual test logic based ON THE HTML PROVIDED. If a field doesn't exist in the HTML, DO NOT test it. Only test the elements that are actually present.
    8. VERY IMPORTANT: You MUST write a detailed Python docstring (`\"\"\"...\"\"\"`) for EVERY test function. The docstring must explain the specific intent of the test and what it verifies. These will be parsed for the final HTML report.
    """
    
    # If this is a retry attempt, feed the failure logs back into the LLM
    if state.get("execution_status") == "failed" and state.get("execution_logs"):
        print("Agent: Analyzing previous failure to heal script...")
        prompt += f"\n\nPREVIOUS RUN FAILED WITH THESE LOGS:\n{state['execution_logs']}\n\nPlease fix the test code to address these exact errors. Ensure selectors match the DOM, or correct any logic bugs."

    response = llm.invoke([HumanMessage(content=prompt)])
    
    # Clean up standard markdown wrapping if LLM includes it
    code = response.content.replace('```python', '').replace('```', '').strip()
    return {"generated_test_code": code}

# ---------------------------------------------------------
# Node 3: Execution Monitor (Local Simulation)
# ---------------------------------------------------------
# In production, this would dispatch to the Docker sandbox. 
# We execute in a `/workspace` directory that can be mounted as a volume.
def execute_tests(state: AgentState):
    code = state["generated_test_code"]
    current_retries = state.get("retry_count", 0)
    
    print(f"Agent: Executing generated test script. Standby...")
    
    # Save code to a mounted workspace directory
    workspace_dir = "/workspace"
    if not os.path.exists(workspace_dir):
        os.makedirs(workspace_dir, exist_ok=True)
        
    test_file_path = os.path.join(workspace_dir, "test_generated.py")
    
    with open(test_file_path, "w") as f:
        f.write(code)
        
    print(f"\n--- GENERATED TEST CODE (Saved to {test_file_path}) ---\n{code}\n---------------------------\n")

    # Inject pytest.ini to define metadata and project name
    pytest_ini_path = os.path.join(workspace_dir, "pytest.ini")
    with open(pytest_ini_path, "w") as f:
        f.write(f"""[pytest]
addopts = 
    --html={os.path.join(workspace_dir, 'report.html')} 
    --self-contained-html
    --css={os.path.join(workspace_dir, 'custom.css')}
    --tracing=retain-on-failure
    --output={os.path.join(workspace_dir, 'test-results')}

metadata =
    Project AI Testing Agent
    Target_URL {state.get('target_url', 'Unknown')}
    PR_Description {state.get('pr_description', 'No description provided').replace(chr(10), ' ')}
""")

    # Inject custom CSS for a better UI report
    custom_css_path = os.path.join(workspace_dir, "custom.css")
    with open(custom_css_path, "w") as f:
        f.write("""
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background-color: #f8f9fa; color: #333; margin: 0; padding: 20px; }
        h1 { color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }
        .summary { background: #fff; border-radius: 8px; padding: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); margin-bottom: 20px;}
        .results-table { width: 100%; border-collapse: collapse; margin-top: 20px; background: #fff; box-shadow: 0 4px 6px rgba(0,0,0,0.1); border-radius: 8px; overflow: hidden; }
        .results-table th { background-color: #34495e; color: white; padding: 12px; text-align: left; }
        .results-table td { padding: 12px; border-bottom: 1px solid #ecf0f1; }
        .passed { color: #27ae60; font-weight: bold; }
        .failed { color: #e74c3c; font-weight: bold; }
        .log { background: #2c3e50; color: #ecf0f1; padding: 10px; border-radius: 4px; font-family: monospace; white-space: pre-wrap; margin-top: 10px; }
        """)

    # Inject conftest.py to dynamically add extra Context links and Docstrings to the HTML report
    conftest_path = os.path.join(workspace_dir, "conftest.py")
    with open(conftest_path, "w") as f:
        f.write("""
import pytest
from datetime import datetime

def pytest_html_report_title(report):
    report.title = "Autonomous AI Testing Report"

def pytest_html_results_table_header(cells):
    cells.insert(2, "<th>Description</th>")
    cells.insert(1, '<th class="sortable time" data-column-type="time">Time</th>')

def pytest_html_results_table_row(report, cells):
    cells.insert(2, f"<td>{report.description}</td>")
    cells.insert(1, f'<td class="col-time">{datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")}</td>')

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    # Attach the python docstring to the report row for better explanation
    report.description = str(item.function.__doc__) if item.function.__doc__ else 'N/A'
""")
    
    # Execute the test using pytest
    import subprocess
    result = subprocess.run(
        [
            "pytest", 
            test_file_path, 
            "-v", 
            "--tb=short",
            f"--html={os.path.join(workspace_dir, 'report.html')}",
            f"--tracing=retain-on-failure",
            f"--output={os.path.join(workspace_dir, 'test-results')}"
        ], 
        capture_output=True, 
        text=True
    )
    
    status = "success" if result.returncode == 0 else "failed"
    logs = result.stdout + "\n" + result.stderr
    
    print(f"Agent: Execution finished with status: {status.upper()}")
    if status == "failed":
        print(f"Agent: Errors detected. Preparing to self-heal.")
        print(f"--- PYTEST LOGS ---\n{logs}\n-------------------")
        
    return {
        "execution_status": status,
        "execution_logs": logs,
        "retry_count": current_retries + 1
    }
            
# ---------------------------------------------------------
# Graph Routing Logic
# ---------------------------------------------------------
def should_continue(state: AgentState):
    """Determine whether to finish, or loop back and try to heal the test script."""
    if state.get("execution_status") == "success":
        print("Agent: Tests passed successfully! Agent task complete.")
        return END
    
    # If failed, but we haven't hit the retry limit, try again
    if state.get("retry_count", 0) < 3:
        return "generate_tests"
        
    print("Agent: Maximum retries (3) reached. Test failing.")
    return END

# ---------------------------------------------------------
# Blueprint compilation
# ---------------------------------------------------------
def create_agent():
    workflow = StateGraph(AgentState)

    # Add nodes
    workflow.add_node("analyze_requirements", analyze_requirements)
    workflow.add_node("generate_tests", generate_tests)
    workflow.add_node("execute_tests", execute_tests)

    # Define edges: Default flow
    workflow.set_entry_point("analyze_requirements")
    workflow.add_edge("analyze_requirements", "generate_tests")
    workflow.add_edge("generate_tests", "execute_tests")
    
    # Define conditional edges: Loop or Exit based on success/retries
    workflow.add_conditional_edges(
        "execute_tests",
        should_continue,
        {
            END: END,
            "generate_tests": "generate_tests"
        }
    )

    return workflow.compile()

# Runner
if __name__ == "__main__":
    import sys
    app = create_agent()
    
    # Read from sys.argv if provided (CI/CD mode)
    if len(sys.argv) > 3:
        pr_number = sys.argv[1]
        pr_body = sys.argv[2]
        target_url = sys.argv[3]
        pr_description = f"PR #{pr_number}: {pr_body}"
        print(f"Starting in CI/CD Mode targeting {target_url}")
    else:
        # Default fallback for local testing
        pr_description = "Added a new 'Submit Order' button on the checkout page."
        target_url = "https://example.com/checkout"
        print("Starting in Local Dev Mode")
        
    initial_state = {
        "pr_description": pr_description,
        "target_url": target_url,
        "retry_count": 0,
        "execution_status": "pending",
        "execution_logs": ""
    }
    
    print("\n--- Starting Autonomous AI Testing Agent ---")
    for event in app.stream(initial_state):
        pass # Nodes will print their own status

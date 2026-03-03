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
    5. Include comments explaining the test steps.
    6. Ensure the test uses headless mode.
    7. Set a very short timeout for page actions, e.g. `page.set_default_timeout(3000)` so tests fail fast if selectors are wrong.
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
# For local testing, we execute in a temporary directory.
def execute_tests(state: AgentState):
    code = state["generated_test_code"]
    current_retries = state.get("retry_count", 0)
    
    print(f"Agent: Executing generated test script. Standby...")
    
    # Save code to a temporary test file
    import tempfile
    test_dir = tempfile.mkdtemp()
    test_file_path = os.path.join(test_dir, "test_generated.py")
    
    try:
        with open(test_file_path, "w") as f:
            f.write(code)
            
        print(f"\n--- GENERATED TEST CODE ---\n{code}\n---------------------------\n")
        
        # Execute the test using pytest
        import subprocess
        result = subprocess.run(
            ["pytest", test_file_path, "-v", "--tb=short"], 
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
    finally:
        # Cleanup
        if os.path.exists(test_file_path):
            os.remove(test_file_path)
            
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

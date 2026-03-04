"""
Page Inspector Tool
-------------------
Uses Playwright to visit a URL and extract all interactive elements
(form fields, buttons, headings, success/error message elements) from the DOM.
Returns a human-readable context string that the LLM uses to generate
accurate tests with real selectors instead of hallucinated ones.
"""

from playwright.sync_api import sync_playwright


def inspect_page(url: str) -> str:
    """
    Visit `url` using a headless Chromium browser and extract:
      - Page title
      - All headings (h1-h3)
      - All <input> elements (id, name, type, placeholder, required)
      - All <button> elements (id, text)
      - All <a> elements with id or noticeable text
      - Elements that look like feedback divs (ids containing 'msg', 'error', 'success', 'alert')

    Returns a structured string summary for injection into the LLM prompt.
    """
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_default_timeout(10000)
            page.goto(url, wait_until="domcontentloaded")

            lines = [f"--- DOM INSPECTION REPORT for {url} ---"]

            # Title
            title = page.title()
            lines.append(f"Page Title: {title}")

            # Headings
            headings = page.query_selector_all("h1, h2, h3")
            if headings:
                lines.append("\nHeadings:")
                for h in headings:
                    text = h.inner_text().strip()
                    tag = h.evaluate("el => el.tagName.toLowerCase()")
                    if text:
                        lines.append(f"  <{tag}>: \"{text}\"")

            # Input elements
            inputs = page.query_selector_all("input, select, textarea")
            if inputs:
                lines.append("\nForm Fields:")
                for inp in inputs:
                    el_id = inp.get_attribute("id") or ""
                    el_name = inp.get_attribute("name") or ""
                    el_type = inp.get_attribute("type") or "text"
                    el_placeholder = inp.get_attribute("placeholder") or ""
                    el_required = inp.get_attribute("required")
                    required_str = " [REQUIRED]" if el_required is not None else ""
                    id_str = f'id="{el_id}"' if el_id else ""
                    name_str = f'name="{el_name}"' if el_name else ""
                    lines.append(
                        f"  <input type=\"{el_type}\" {id_str} {name_str} "
                        f'placeholder="{el_placeholder}"{required_str}>'
                    )

            # Buttons
            buttons = page.query_selector_all("button, input[type='submit'], input[type='button']")
            if buttons:
                lines.append("\nButtons:")
                for btn in buttons:
                    btn_id = btn.get_attribute("id") or ""
                    btn_text = btn.inner_text().strip() if btn.inner_text() else btn.get_attribute("value") or ""
                    btn_type = btn.get_attribute("type") or "button"
                    lines.append(f'  <button id="{btn_id}" type="{btn_type}">: "{btn_text}"')

            # Feedback / message divs
            feedback_candidates = page.query_selector_all(
                "div[id], span[id], p[id]"
            )
            feedback_lines = []
            for el in feedback_candidates:
                el_id = el.get_attribute("id") or ""
                keywords = ["msg", "error", "success", "alert", "warn", "info", "notification", "feedback"]
                if any(kw in el_id.lower() for kw in keywords):
                    el_text = el.evaluate("el => el.textContent.trim()")
                    el_class = el.get_attribute("class") or ""
                    el_visible = el.is_visible()
                    visibility_note = "" if el_visible else " [hidden by default]"
                    feedback_lines.append(
                        f'  id="{el_id}" class="{el_class}"{visibility_note}: "{el_text}"'
                    )
            if feedback_lines:
                lines.append("\nFeedback / Message Elements (for assertions):")
                lines.extend(feedback_lines)

            browser.close()

            lines.append("\n--- END DOM INSPECTION REPORT ---")
            report = "\n".join(lines)
            print(f"Page Inspector: Successfully inspected {url}")
            return report

    except Exception as e:
        error_msg = f"Page Inspector ERROR: Could not inspect {url}. Reason: {e}"
        print(error_msg)
        return error_msg

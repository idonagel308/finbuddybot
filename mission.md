# 🚨 Mission: Stabilize & Upgrade FinTech Bot

## Diagnosis: Why is "Something went wrong" still happening?
The bot is receiving messages correctly via webhook, but the LLM parsing is failing. The Cloud Run and local logs show:
```
parse_expense: gemini-pro: NotFound - 404 models/gemini-pro is not found for API version v1...
```
**Root Cause Hypothesis:**
1. We are using the `google-generativeai` package (which is now officially deprecated by Google).
2. We are asking for `gemini-2.5-flash` or `gemini-1.5-flash`. The old SDK uses the older `v1` API endpoint, which no longer recognizes these models in the same way, or defaults to `gemini-pro` (which was sunset/removed), causing a hard 404 crash.
3. The LLM parsing fails, and the fallback regex logic is either skipped or failing because of the exception handling.

To fix this smartly, we will split the work into two independent branches so two agents can tackle it in parallel without stepping on each other's toes.

---

## Branch A: The Modernization Branch
**Focus**: Upgrade the LLM engine to the official, supported Google GenAI SDK.
**Assignee**: Agent 1 (Me)

### Tasks:
1. **Update Dependencies**:
   - Remove `google-generativeai` from `requirements.txt`.
   - Add the new official SDK: `google-genai>=0.3.0`.
2. **Refactor `llm_helper.py`**:
   - Rewrite the Gemini initialization to use `from google import genai` and `client = genai.Client(api_key=...)`.
   - Update `parse_expense`, `translate`, and `generate_insights` to use the new `client.models.generate_content()` syntax.
   - Ensure the model name is strictly `gemini-2.5-flash`.
3. **Verify Locally**:
   - Run the updated `llm_helper.py` script as `__main__` to ensure the new SDK correctly parses an expense without 404 errors.

---

## Branch B: The Resilience Branch
**Focus**: Ensure the application never fully crashes even if the AI is completely offline or throwing 404/500 errors.
**Assignee**: Agent 2 (The other agent)

### Tasks:
1. **Bulletproof Exception Handling in `callbacks.py / messages.py`**:
   - Currently, if `parse_expense` fails completely or returns `None`, the whole bot throws an uncaught exception (`Something went wrong`). Ensure these are caught cleanly, informing the user "AI is currently unavailable, we saved your text, please edit manually."
2. **Robustify the Regex Fallback**:
   - In `llm_helper.py`, if the LLM crashes, the regex fallback currently runs. Verify that the regex fallback actually works and doesn't crash on its own logic (e.g., `text_lower` might be unbound if an exception jumps out early).
3. **Graceful Degradation Tests**:
   - Add a test in `test_suite.py` that explicitly removes the `GOOGLE_API_KEY` (or sets it to "INVALID") and verifies that the bot can STILL parse simple statements using ONLY the regex fallback.

---

## Workflow Instructions
*   **Agent 1 (Current Agent)** will execute **Branch A**.
*   Please provide this `mission.md` document to the **second agent** and instruct them to execute **Branch B**.
*   Once both branches are complete, we will merge the code, run the full test suite, and deploy to Cloud Run.

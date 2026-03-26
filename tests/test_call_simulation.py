"""Text-only simulation of CareCaller calls via Groq LLM.
Tests that the agent follows the call flow, calls tools correctly across different scenarios.
No voice/LiveKit needed — just hits the LLM directly.

Usage:
  uv run tests/test_call_simulation.py                 # run all scenarios
  uv run tests/test_call_simulation.py happy_path      # run one scenario
"""

import json
import os
import sys

from dotenv import load_dotenv
from groq import Groq

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from config import DEFAULT_PATIENT, HEALTH_QUESTIONS
from prompts import SYSTEM_PROMPT

load_dotenv(".env.local")

client = Groq()
MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "record_answer",
            "description": (
                "Record the patient's answer to a health questionnaire question. "
                "Call this IMMEDIATELY after the patient answers each health question. "
                "question_index: 0-13 matching the question order. "
                "answer: The patient's answer summarized concisely."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question_index": {"type": "integer", "description": "0-13"},
                    "answer": {"type": "string", "description": "Patient's answer"},
                },
                "required": ["question_index", "answer"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_call_outcome",
            "description": (
                "Set the final outcome of this call. Call this BEFORE ending the call. "
                "outcome must be one of: completed, incomplete, opted_out, scheduled, escalated, wrong_number, voicemail."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "outcome": {"type": "string"},
                },
                "required": ["outcome"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "end_call",
            "description": (
                "End the call. Use this when the conversation is complete, the patient opts out, "
                "it's a wrong number, or the patient wants to hang up. "
                "IMPORTANT: Always call set_call_outcome BEFORE calling end_call."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
]

# ── Scenarios ──────────────────────────────────────────────

SCENARIOS = {
    "happy_path": {
        "description": "Patient confirms identity, answers all 14 questions",
        "patient_responses": [
            "Yes, this is Sarah.",
            "Yes, I'd like my refill.",
            "Sure, go ahead.",
            "I've been feeling pretty good.",
            "I'm at 185 pounds.",
            "5 foot 7.",
            "I lost about 4 pounds.",
            "No side effects.",
            "Yeah, I'm happy with it.",
            "I'd like to get to 160.",
            "No, the dosage is fine.",
            "No new medications.",
            "No new conditions.",
            "No new allergies.",
            "No surgeries.",
            "No questions for the doctor.",
            "No, same address.",
            "Thanks, bye!",
        ],
        "expected_outcome": "completed",
        "expected_min_answers": 14,
    },
    # voicemail: skipped — requires voice/timing (no silence detection in text simulation)
    "opted_out": {
        "description": "Patient declines the refill",
        "patient_responses": [
            "Yes, this is Sarah.",
            "No, I'm not interested anymore.",
            "Yeah, I'm sure. Thanks though.",
        ],
        "expected_outcome": "opted_out",
        "expected_min_answers": 0,
    },
    "wrong_number": {
        "description": "Wrong person answers the phone",
        "patient_responses": [
            "No, you've got the wrong number.",
            "Yeah, wrong person.",
        ],
        "expected_outcome": "wrong_number",
        "expected_min_answers": 0,
    },
    "incomplete": {
        "description": "Patient leaves mid-questionnaire after a few questions",
        "patient_responses": [
            "Yes, this is Sarah.",
            "Yes, I want the refill.",
            "Sure, go ahead.",
            "Feeling okay.",
            "192 pounds.",
            "5 foot 5.",
            "About 3 pounds.",
            "Sorry, I have to go. Something came up. Bye.",
        ],
        "expected_outcome": "incomplete",
        "expected_min_answers": 3,
    },
    "escalation": {
        "description": "Patient reports concerning symptoms and needs escalation",
        "patient_responses": [
            "Yes, this is Sarah.",
            "Yes, I want the refill.",
            "Sure, go ahead.",
            "Not great, I've been having chest pains and severe dizziness.",
            "I really need to talk to a doctor about this right away.",
        ],
        "expected_outcome": "escalated",
        "expected_min_answers": 0,
    },
    "reschedule": {
        "description": "Patient doesn't have time right now",
        "patient_responses": [
            "Yes, this is Sarah.",
            "Yes, I want my refill.",
            "Actually no, I'm really busy. Can you call back tomorrow?",
            "Tomorrow afternoon works.",
        ],
        "expected_outcome": "scheduled",
        "expected_min_answers": 0,
    },
}


def run_scenario(name: str, scenario: dict) -> dict:
    patient = DEFAULT_PATIENT
    system_prompt = SYSTEM_PROMPT.format(**patient)
    patient_responses = scenario["patient_responses"]

    messages = [{"role": "system", "content": system_prompt}]
    responses_captured: dict[int, str] = {}
    outcome_captured: str | None = None
    patient_idx = 0
    call_ended = False

    print(f"\n{'=' * 60}")
    print(f"SCENARIO: {name}")
    print(f"Description: {scenario['description']}")
    print(f"{'=' * 60}\n")

    response = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        tools=TOOLS,
        tool_choice="auto",
    )

    for turn in range(50):
        msg = response.choices[0].message
        messages.append(msg)

        if msg.tool_calls:
            for tc in msg.tool_calls:
                args = json.loads(tc.function.arguments)
                tool_name = tc.function.name

                if tool_name == "record_answer":
                    idx = int(args["question_index"])
                    ans = args["answer"]
                    if 0 <= idx < len(HEALTH_QUESTIONS):
                        responses_captured[idx] = ans
                        result = f"Recorded answer for question {idx + 1}/{len(HEALTH_QUESTIONS)}."
                        print(f"  [TOOL] record_answer(Q{idx}) -> \"{ans}\"")
                    else:
                        result = f"Invalid question_index {idx}."
                        print(f"  [TOOL] record_answer(Q{idx}) -> INVALID INDEX")

                elif tool_name == "set_call_outcome":
                    outcome_captured = args["outcome"]
                    result = f"Outcome set to '{outcome_captured}'."
                    print(f"  [TOOL] set_call_outcome -> \"{outcome_captured}\"")

                elif tool_name == "end_call":
                    result = "Call ended."
                    call_ended = True
                    print("  [TOOL] end_call")

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

            if call_ended:
                break

            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
            )
            continue

        if msg.content:
            print(f"[AGENT]: {msg.content}")

        if call_ended:
            break

        if patient_idx < len(patient_responses):
            patient_msg = patient_responses[patient_idx]
            patient_idx += 1
            print(f"[PATIENT]: {patient_msg}")
            messages.append({"role": "user", "content": patient_msg})
        else:
            break

        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
        )

    # ── Results ──
    expected_outcome = scenario["expected_outcome"]
    expected_min = scenario["expected_min_answers"]
    num_answers = len(responses_captured)

    checks = []
    passed = True

    # Check outcome
    if outcome_captured == expected_outcome:
        checks.append(f"  [PASS] Outcome: {outcome_captured}")
    else:
        checks.append(f"  [FAIL] Outcome: expected '{expected_outcome}', got '{outcome_captured}'")
        passed = False

    # Check answer count
    if num_answers >= expected_min:
        checks.append(f"  [PASS] Answers: {num_answers} (min expected: {expected_min})")
    else:
        checks.append(f"  [FAIL] Answers: {num_answers} (min expected: {expected_min})")
        passed = False

    # Check end_call
    if call_ended:
        checks.append("  [PASS] end_call was called")
    else:
        checks.append("  [FAIL] end_call was NOT called")
        passed = False

    print(f"\n--- {name} results ---")
    for c in checks:
        print(c)
    print(f"  {'PASSED' if passed else 'FAILED'}")

    return {"name": name, "passed": passed, "outcome": outcome_captured, "answers": num_answers}


def main():
    scenarios_to_run = sys.argv[1:] if len(sys.argv) > 1 else list(SCENARIOS.keys())

    results = []
    for name in scenarios_to_run:
        if name not in SCENARIOS:
            print(f"Unknown scenario: {name}")
            print(f"Available: {', '.join(SCENARIOS.keys())}")
            sys.exit(1)
        results.append(run_scenario(name, SCENARIOS[name]))

    # Summary
    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print(f"{'=' * 60}")
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        print(f"  [{status}] {r['name']} (outcome={r['outcome']}, answers={r['answers']})")

    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    print(f"\n{passed}/{total} scenarios passed")

    if passed < total:
        sys.exit(1)


if __name__ == "__main__":
    main()

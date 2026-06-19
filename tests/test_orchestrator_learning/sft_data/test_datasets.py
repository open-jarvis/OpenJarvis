"""Offline tests for the reasoning-SFT dataset loaders.

All loaders take a ``source=`` iterable of raw row dicts so we never touch the
network: we hand them fake rows shaped like the real GeneralThought /
OpenThoughts3 schemas and assert the normalized :class:`Task` fields.
"""

from __future__ import annotations

from openjarvis.learning.intelligence.orchestrator.sft_data.datasets import (
    Task,
    load_generalthought,
    load_openthoughts,
)

# --- fake rows mirroring the real HF schemas ---------------------------------

GENERALTHOUGHT_ROWS = [
    {
        "question_id": 1,
        "question": "What is 2 + 2?",
        "reference_answer": "4",
        "model_answer": "The answer is 4.",
        "task": "High School Math",
        "question_source": "Numina/NuminaMath",
    },
    {
        "question_id": 2,
        "question": "How do the neural respiratory centers operate?",
        "reference_answer": "Via the medulla oblongata.",
        "model_answer": "long answer ...",
        "task": "NHS QA",
        "question_source": "CogStack/NHSQA",
    },
    {
        "question_id": 3,
        "question": "Sort a list.",
        "reference_answer": "",
        "model_answer": "use sorted()",
        "task": "Sorting",
        "question_source": "BAAI/TACO",
    },
    # Should be skipped: empty question and answer.
    {"question_id": 4, "question": "", "reference_answer": "", "model_answer": ""},
]

OPENTHOUGHTS_ROWS = [
    {
        "domain": "code",
        "source": "stackexchange_codegolf",
        "difficulty": 7,
        "conversations": [
            {"from": "human", "value": "Write a program that prints hi."},
            {"from": "gpt", "value": "<think>reason</think> Final: print('hi')"},
        ],
    },
    {
        "domain": "math",
        "source": "Numina/NuminaMath",
        "difficulty": 5,
        "conversations": [
            {"from": "human", "value": "What is 6 times 7?"},
            {"from": "gpt", "value": "<think>6*7=42</think> The answer is \\boxed{42}."},
        ],
    },
    {
        "domain": "science",
        "source": "sci",
        "difficulty": 6,
        "conversations": [
            {"from": "human", "value": "What gas do plants release?"},
            {"from": "gpt", "value": "Oxygen."},
        ],
    },
    # Should be skipped: no human/gpt turns.
    {"domain": "math", "conversations": []},
]


def test_load_generalthought_fields_and_domains():
    tasks = list(load_generalthought(n=10, source=GENERALTHOUGHT_ROWS))
    assert all(isinstance(t, Task) for t in tasks)
    # Row 4 (empty) is dropped; remaining 3 yielded.
    assert len(tasks) == 3
    by_q = {t.question: t for t in tasks}
    assert by_q["What is 2 + 2?"].answer == "4"
    assert by_q["What is 2 + 2?"].domain == "math"
    assert by_q["What is 2 + 2?"].instruction == "What is 2 + 2?"
    assert by_q["How do the neural respiratory centers operate?"].domain == "medical"
    # No reference_answer -> falls back to model_answer; TACO source -> code.
    assert by_q["Sort a list."].answer == "use sorted()"
    assert by_q["Sort a list."].domain == "code"


def test_load_generalthought_respects_n():
    tasks = list(load_generalthought(n=2, source=GENERALTHOUGHT_ROWS))
    assert len(tasks) == 2


def test_load_openthoughts_fields_and_domains():
    tasks = list(
        load_openthoughts(
            n_code=5, n_math=5, n_science=5, source=OPENTHOUGHTS_ROWS
        )
    )
    assert all(isinstance(t, Task) for t in tasks)
    assert len(tasks) == 3
    by_dom = {t.domain: t for t in tasks}
    assert set(by_dom) == {"code", "math", "science"}
    # <think> stripped; boxed answer extracted.
    assert by_dom["math"].answer == "42"
    assert by_dom["math"].question == "What is 6 times 7?"
    # Code: think stripped, visible solution kept.
    assert "print('hi')" in by_dom["code"].answer
    assert by_dom["science"].answer == "Oxygen."


def test_load_openthoughts_quota_caps_per_domain():
    rows = [
        {
            "domain": "code",
            "conversations": [
                {"from": "human", "value": f"q{i}"},
                {"from": "gpt", "value": f"a{i}"},
            ],
        }
        for i in range(10)
    ]
    tasks = list(load_openthoughts(n_code=3, n_math=0, n_science=0, source=rows))
    assert len(tasks) == 3
    assert all(t.domain == "code" for t in tasks)


def test_task_dataclass_instruction_property():
    t = Task(task_id="x", question="hi?", answer="yes", domain="misc")
    assert t.instruction == "hi?"

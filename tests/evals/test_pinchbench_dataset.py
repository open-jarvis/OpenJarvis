"""Tests for PinchBench dataset provider."""

import textwrap

from openjarvis.evals.datasets.pinchbench import _parse_task_markdown


def test_parse_task_markdown_basic():
    """Parse a minimal task markdown file."""
    md = textwrap.dedent("""\
    ---
    id: task_00_test
    name: Test Task
    category: basic
    grading_type: automated
    timeout_seconds: 60
    workspace_files: []
    ---

    ## Prompt

    Do the thing.

    ## Expected Behavior

    The thing should be done.

    ## Grading Criteria

    - [ ] Thing was done

    ## Automated Checks

    ```python
    def grade(transcript, workspace_path):
        return {"done": 1.0}
    ```
    """)
    task = _parse_task_markdown(md, filename="task_00_test.md")
    assert task["id"] == "task_00_test"
    assert task["name"] == "Test Task"
    assert task["category"] == "basic"
    assert task["grading_type"] == "automated"
    assert "Do the thing." in task["prompt"]
    assert "The thing should be done." in task["expected_behavior"]
    assert "def grade" in task["automated_checks"]


def test_parse_task_markdown_hybrid():
    """Parse a hybrid-graded task with weights."""
    md = textwrap.dedent("""\
    ---
    id: task_16_triage
    name: Email Triage
    category: email
    grading_type: hybrid
    timeout_seconds: 300
    workspace_files:
      - source: emails/email_01.txt
        dest: inbox/email_01.txt
    grading_weights:
      automated: 0.4
      llm_judge: 0.6
    ---

    ## Prompt

    Triage the emails.

    ## Expected Behavior

    Create a report.

    ## Grading Criteria

    - [ ] Report created

    ## Automated Checks

    ```python
    def grade(transcript, workspace_path):
        return {"report": 1.0}
    ```

    ## LLM Judge Rubric

    ### Criterion 1: Quality (Weight: 100%)

    **Score 1.0**: Excellent
    """)
    task = _parse_task_markdown(md, filename="task_16_triage.md")
    assert task["grading_type"] == "hybrid"
    assert task["grading_weights"] == {"automated": 0.4, "llm_judge": 0.6}
    assert len(task["workspace_files"]) == 1
    assert "Quality" in task["llm_judge_rubric"]


def test_parse_task_markdown_no_automated_checks():
    """LLM-judge-only tasks have no automated checks."""
    md = textwrap.dedent("""\
    ---
    id: task_03_blog
    name: Blog Post
    category: writing
    grading_type: llm_judge
    timeout_seconds: 180
    workspace_files: []
    ---

    ## Prompt

    Write a blog post.

    ## Expected Behavior

    A good blog post.

    ## Grading Criteria

    - [ ] Well written

    ## LLM Judge Rubric

    ### Writing (Weight: 100%)

    **Score 1.0**: Excellent
    """)
    task = _parse_task_markdown(md, filename="task_03_blog.md")
    assert task["automated_checks"] is None
    assert "Writing" in task["llm_judge_rubric"]

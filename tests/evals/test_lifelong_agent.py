"""Tests for LifelongAgentBench benchmark.

Covers:
- DB building and state comparison
- DB scoring (direct SELECT + md5 DML)
- SQL extraction (original's Action: Operation format)
- Text answer parsing (DirectTypeAnswerValidator format)
- KG answer extraction and scoring (exact match + F1)
- OS scoring (Docker check)
- Value comparison with numeric tolerance
- Episode grouping for lifelong learning
- Dataset instantiation and CLI wiring
- Multi-turn environment interaction (DB, KG, OS)
- Interactive runner integration
"""

import json

from openjarvis.evals.core.types import EvalRecord
from openjarvis.evals.datasets.lifelong_agent import LifelongAgentDataset
from openjarvis.evals.scorers.lifelong_agent_scorer import (
    LifelongAgentScorer,
    _compare_table_states,
    _extract_bash_commands,
    _get_table_rows,
    _hash_table_state,
    _parse_text_answer,
    build_db,
    compare_tuple_lists,
    extract_kg_answers,
    extract_sql,
    values_match,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_TABLE_INFO = {
    "name": "users",
    "column_info_list": [
        {"name": "id", "type": "INT"},
        {"name": "name", "type": "TEXT"},
        {"name": "score", "type": "FLOAT"},
    ],
    "row_list": [
        [1, "Alice", 95.5],
        [2, "Bob", 87.0],
        [3, "Carol", 92.3],
    ],
}


def _db_record(direct=None, md5=None, sql="SELECT * FROM users", skills=None):
    answer_info = {"direct": direct, "md5": md5, "sql": sql}
    answer_type = "md5" if md5 else "direct"
    return EvalRecord(
        record_id="test-1",
        problem="task",
        reference=json.dumps(answer_info),
        category="agentic",
        subject=f"db_{answer_type}",
        metadata={
            "answer_info": answer_info,
            "answer_type": answer_type,
            "skills": skills or [],
            "table_info": _TABLE_INFO,
            "table_name": "users",
            "subset": "db_bench",
            "sample_index": 0,
        },
    )


def _kg_record(answer_list=None, skills=None, action_list=None):
    return EvalRecord(
        record_id="test-kg-1",
        problem="question",
        reference=json.dumps(answer_list or []),
        category="agentic",
        subject="knowledge_graph",
        metadata={
            "subset": "knowledge_graph",
            "question": "What is the answer?",
            "answer_list": answer_list or [],
            "action_list": action_list or [],
            "entity_dict": {},
            "skills": skills or [],
            "sample_index": 0,
        },
    )


def _os_record():
    return EvalRecord(
        record_id="test-os-1",
        problem="task",
        reference="{}",
        category="agentic",
        subject="os_interaction",
        metadata={
            "subset": "os_interaction",
            "instruction": "Create a file",
            "skills": ["bash"],
            "init_command": {"command_name": "bash", "script": "echo init"},
            "evaluation_info": {
                "evaluation_command_item": {
                    "command_name": "bash",
                    "script": "test -f /tmp/testfile && exit 0 || exit 1",
                },
            },
            "evaluation_command": {
                "command_name": "bash",
                "script": "test -f /tmp/testfile && exit 0 || exit 1",
            },
            "sample_index": 0,
        },
    )


# ---------------------------------------------------------------------------
# DB building
# ---------------------------------------------------------------------------


class TestBuildDB:
    def test_creates_table_with_rows(self) -> None:
        conn = build_db(_TABLE_INFO)
        rows = conn.execute("SELECT * FROM users").fetchall()
        assert len(rows) == 3
        assert rows[0] == (1, "Alice", 95.5)
        conn.close()

    def test_select_works(self) -> None:
        conn = build_db(_TABLE_INFO)
        rows = conn.execute("SELECT name FROM users WHERE score > 90").fetchall()
        names = [r[0] for r in rows]
        assert "Alice" in names and "Carol" in names and "Bob" not in names
        conn.close()

    def test_insert_modifies_state(self) -> None:
        conn = build_db(_TABLE_INFO)
        conn.execute("INSERT INTO users VALUES (4, 'Dave', 88.0)")
        conn.commit()
        assert len(conn.execute("SELECT * FROM users").fetchall()) == 4
        conn.close()

    def test_empty_table_info(self) -> None:
        conn = build_db({"name": "empty", "column_info_list": [], "row_list": []})
        rows = conn.execute("SELECT * FROM empty").fetchall()
        assert len(rows) == 0
        conn.close()


class TestTableStateComparison:
    def test_hash_consistent(self) -> None:
        rows1 = _get_table_rows(build_db(_TABLE_INFO), "users")
        rows2 = _get_table_rows(build_db(_TABLE_INFO), "users")
        assert _hash_table_state(rows1) == _hash_table_state(rows2)

    def test_hash_changes_after_insert(self) -> None:
        conn = build_db(_TABLE_INFO)
        rows_before = _get_table_rows(conn, "users")
        conn.execute("INSERT INTO users VALUES (4, 'Dave', 88.0)")
        conn.commit()
        rows_after = _get_table_rows(conn, "users")
        assert _hash_table_state(rows_before) != _hash_table_state(rows_after)
        conn.close()

    def test_direct_comparison_match(self) -> None:
        rows = _get_table_rows(build_db(_TABLE_INFO), "users")
        ok, detail = _compare_table_states(rows, rows)
        assert ok is True
        assert detail == "all_match"

    def test_direct_comparison_row_count(self) -> None:
        rows = _get_table_rows(build_db(_TABLE_INFO), "users")
        ok, detail = _compare_table_states(rows, rows[:2])
        assert ok is False
        assert "row_count_mismatch" in detail


# ---------------------------------------------------------------------------
# SQL extraction (original's Action: Operation format)
# ---------------------------------------------------------------------------


class TestExtractSQL:
    def test_action_operation_format(self) -> None:
        text = "Action: Operation\n```sql\nSELECT * FROM users;\n```"
        assert extract_sql(text) == "SELECT * FROM users;"

    def test_code_block(self) -> None:
        assert extract_sql("```sql\nSELECT 1;\n```") == "SELECT 1;"

    def test_bare_sql(self) -> None:
        assert "SELECT" in extract_sql("SELECT name FROM users")

    def test_operation_prefix(self) -> None:
        assert "SELECT" in extract_sql("Operation: SELECT * FROM users")

    def test_no_sql(self) -> None:
        assert extract_sql("I don't know") == ""

    def test_with_explanation(self) -> None:
        text = (
            "Let me write a SQL query.\n"
            "Action: Operation\n"
            "```sql\n"
            "SELECT name FROM users WHERE score > 90\n"
            "```\n"
        )
        result = extract_sql(text)
        assert "SELECT name FROM users" in result

    def test_insert_statement(self) -> None:
        text = "INSERT INTO users VALUES (4, 'Dave', 88.0)"
        assert "INSERT" in extract_sql(text)


# ---------------------------------------------------------------------------
# Text answer parsing (DirectTypeAnswerValidator format)
# ---------------------------------------------------------------------------


class TestTextAnswerParsing:
    def test_tuple_list(self) -> None:
        text = "Final Answer: [(1, 'Alice', 95.5), (2, 'Bob', 87.0)]"
        result = _parse_text_answer(text)
        assert result is not None
        assert len(result) == 2
        assert result[0][0] == 1

    def test_scalar_answer(self) -> None:
        text = "Final Answer: 42"
        result = _parse_text_answer(text)
        assert result == [[42]]

    def test_string_answer(self) -> None:
        text = "Final Answer: Alice"
        result = _parse_text_answer(text)
        assert result == [["Alice"]]

    def test_action_answer_format(self) -> None:
        text = "Action: Answer\nFinal Answer: [(3, 'Carol')]"
        result = _parse_text_answer(text)
        assert result is not None
        assert result[0] == [3, "Carol"]

    def test_no_final_answer(self) -> None:
        assert _parse_text_answer("I don't know") is None

    def test_comma_separated(self) -> None:
        text = "Final Answer: Alice, Bob, Carol"
        result = _parse_text_answer(text)
        assert result is not None
        assert len(result[0]) == 3


# ---------------------------------------------------------------------------
# DB scorer: direct (SELECT)
# ---------------------------------------------------------------------------


class TestScorerDBDirect:
    def test_correct_sql(self) -> None:
        s = LifelongAgentScorer()
        r = _db_record(
            direct=[[1, "Alice", 95.5], [2, "Bob", 87.0], [3, "Carol", 92.3]],
        )
        ok, meta = s.score(r, "```sql\nSELECT * FROM users;\n```")
        assert ok is True
        assert meta["strategy"] == "sql_execution"

    def test_correct_action_format(self) -> None:
        s = LifelongAgentScorer()
        r = _db_record(
            direct=[[1, "Alice", 95.5], [2, "Bob", 87.0], [3, "Carol", 92.3]],
        )
        ok, meta = s.score(
            r,
            "Action: Operation\n```sql\nSELECT * FROM users\n```",
        )
        assert ok is True

    def test_filtered(self) -> None:
        s = LifelongAgentScorer()
        r = _db_record(
            direct=[[1, "Alice", 95.5]],
            sql="SELECT * FROM users WHERE id = 1",
        )
        ok, _ = s.score(r, "SELECT * FROM users WHERE id = 1")
        assert ok is True

    def test_wrong(self) -> None:
        s = LifelongAgentScorer()
        r = _db_record(direct=[[1, "Alice", 95.5]])
        ok, meta = s.score(r, "SELECT * FROM users")  # 3 rows, expected 1
        assert ok is False

    def test_bad_sql(self) -> None:
        s = LifelongAgentScorer()
        r = _db_record(direct=[[1]])
        ok, meta = s.score(r, "SELECT * FROM nonexistent")
        assert ok is False

    def test_empty(self) -> None:
        ok, _ = LifelongAgentScorer().score(_db_record(direct=[[1]]), "")
        assert ok is False

    def test_no_sql_in_response(self) -> None:
        ok, meta = LifelongAgentScorer().score(
            _db_record(direct=[[1]]),
            "I don't know",
        )
        assert ok is False

    def test_text_answer_fallback(self) -> None:
        s = LifelongAgentScorer()
        r = _db_record(direct=[[1, "Alice", 95.5]])
        ok, meta = s.score(
            r,
            "Action: Answer\nFinal Answer: [(1, 'Alice', 95.5)]",
        )
        assert ok is True
        assert meta["strategy"] == "text_answer_parsing"

    def test_single_shot_warning_in_metadata(self) -> None:
        """Single-shot scoring should include degradation warning."""
        s = LifelongAgentScorer()
        r = _db_record(direct=[[1, "Alice", 95.5]])
        ok, meta = s.score(r, "SELECT * FROM users WHERE id = 1")
        assert meta.get("degraded_single_shot") is True
        assert "warning" in meta


# ---------------------------------------------------------------------------
# DB scorer: md5 (INSERT/UPDATE/DELETE)
# ---------------------------------------------------------------------------


class TestScorerDBMD5:
    def test_correct_insert(self) -> None:
        s = LifelongAgentScorer()
        r = _db_record(md5="x", sql="INSERT INTO users VALUES (4, 'Dave', 88.0)")
        ok, meta = s.score(r, "INSERT INTO users VALUES (4, 'Dave', 88.0)")
        assert ok is True
        assert meta["match_type"] == "md5_table_state"

    def test_wrong_insert(self) -> None:
        s = LifelongAgentScorer()
        r = _db_record(md5="x", sql="INSERT INTO users VALUES (4, 'Dave', 88.0)")
        ok, _ = s.score(r, "INSERT INTO users VALUES (4, 'Eve', 99.0)")
        assert ok is False

    def test_correct_update(self) -> None:
        s = LifelongAgentScorer()
        r = _db_record(md5="x", sql="UPDATE users SET score = 100 WHERE id = 1")
        ok, _ = s.score(r, "UPDATE users SET score = 100 WHERE id = 1")
        assert ok is True

    def test_correct_delete(self) -> None:
        s = LifelongAgentScorer()
        r = _db_record(md5="x", sql="DELETE FROM users WHERE id = 3")
        ok, _ = s.score(r, "DELETE FROM users WHERE id = 3")
        assert ok is True

    def test_action_format(self) -> None:
        s = LifelongAgentScorer()
        r = _db_record(md5="x", sql="INSERT INTO users VALUES (4, 'Dave', 88.0)")
        ok, _ = s.score(
            r,
            "Action: Operation\n```sql\n"
            "INSERT INTO users VALUES (4, 'Dave', 88.0)\n```",
        )
        assert ok is True


# ---------------------------------------------------------------------------
# KG scorer
# ---------------------------------------------------------------------------


class TestScorerKG:
    def test_single_shot_unscorable(self) -> None:
        """KG tasks should be unscorable in single-shot mode."""
        s = LifelongAgentScorer()
        r = _kg_record(answer_list=["m.02h8b9t"])
        ok, meta = s.score(r, "Final Answer: m.02h8b9t")
        assert ok is None
        assert meta["scorable"] is False
        assert meta["match_type"] == "kg_unscorable_single_shot"

    def test_single_shot_returns_none(self) -> None:
        """Any KG single-shot scoring should return None, not False."""
        s = LifelongAgentScorer()
        r = _kg_record(answer_list=["m.001", "m.002"])
        ok, meta = s.score(r, "Final Answer: m.001")
        assert ok is None
        assert meta["scorable"] is False

    def test_skills_propagated(self) -> None:
        s = LifelongAgentScorer()
        r = _kg_record(answer_list=["m.001"], skills=["get_neighbors"])
        _, meta = s.score(r, "Final Answer: m.001")
        assert meta["skills"] == ["get_neighbors"]

    def test_empty_response(self) -> None:
        s = LifelongAgentScorer()
        r = _kg_record(answer_list=["m.001"])
        ok, meta = s.score(r, "")
        assert ok is False
        assert meta["match_type"] == "empty"


# ---------------------------------------------------------------------------
# OS scorer
# ---------------------------------------------------------------------------


class TestScorerOS:
    def test_returns_scorable_status(self) -> None:
        s = LifelongAgentScorer()
        ok, meta = s.score(_os_record(), "echo hello")
        # Without Docker: ok=None, scorable=False
        # With Docker: ok=True/False, scorable=True
        if meta.get("scorable") is False:
            assert ok is None


# ---------------------------------------------------------------------------
# KG answer extraction
# ---------------------------------------------------------------------------


class TestExtractKGAnswers:
    def test_entity_id(self) -> None:
        assert extract_kg_answers("Final Answer: m.02h8b9t") == ["m.02h8b9t"]

    def test_multiple(self) -> None:
        result = extract_kg_answers("Final Answer: m.001, m.002")
        assert set(result) == {"m.001", "m.002"}

    def test_g_prefix(self) -> None:
        result = extract_kg_answers("Final Answer: g.11b7n")
        assert result == ["g.11b7n"]

    def test_text_answer(self) -> None:
        result = extract_kg_answers("Final Answer: New York City")
        assert "New York City" in result

    def test_no_final_answer(self) -> None:
        result = extract_kg_answers("The answer is m.001")
        assert "m.001" in result

    def test_empty_text(self) -> None:
        assert extract_kg_answers("") == []


# ---------------------------------------------------------------------------
# Bash command extraction
# ---------------------------------------------------------------------------


class TestExtractBashCommands:
    def test_act_format(self) -> None:
        text = "Act: ```bash\nls -la /tmp\n```"
        cmds = _extract_bash_commands(text)
        assert len(cmds) == 1
        assert "ls -la" in cmds[0]

    def test_code_block(self) -> None:
        text = "```bash\ncat /etc/passwd\n```"
        cmds = _extract_bash_commands(text)
        assert len(cmds) == 1

    def test_multiple_commands(self) -> None:
        text = (
            "Act: ```bash\nmkdir /tmp/test\n```\n"
            "Act: ```bash\ntouch /tmp/test/file.txt\n```"
        )
        cmds = _extract_bash_commands(text)
        assert len(cmds) == 2

    def test_no_commands(self) -> None:
        assert _extract_bash_commands("I'm not sure") == []


# ---------------------------------------------------------------------------
# Value comparison
# ---------------------------------------------------------------------------


class TestValueComparison:
    def test_int(self) -> None:
        assert values_match(42, 42)

    def test_float_tol(self) -> None:
        assert values_match(1.0, 1.0 + 1e-8)

    def test_float_too_far(self) -> None:
        assert not values_match(1.0, 1.1)

    def test_string(self) -> None:
        assert values_match("hello", "hello")

    def test_none(self) -> None:
        assert values_match(None, None)
        assert not values_match(None, 1)

    def test_cross_type(self) -> None:
        assert values_match(42, "42")
        assert values_match(5, 5.0)

    def test_string_whitespace(self) -> None:
        assert values_match(" hello ", "hello")


class TestTupleComparison:
    def test_match(self) -> None:
        ok, _ = compare_tuple_lists([[1, 2]], [[1, 2]])
        assert ok

    def test_row_mismatch(self) -> None:
        ok, d = compare_tuple_lists([[1], [2]], [[1]])
        assert not ok and "row_count" in d

    def test_col_mismatch(self) -> None:
        ok, d = compare_tuple_lists([[1, 2]], [[1]])
        assert not ok and "col_count" in d


# ---------------------------------------------------------------------------
# Episode grouping
# ---------------------------------------------------------------------------


class TestEpisodeGrouping:
    def test_single_subset_episode(self) -> None:
        ds = LifelongAgentDataset(subset="db_bench")
        ds._records = [
            EvalRecord(
                record_id=f"lifelong-db-{i}",
                problem="task",
                reference="{}",
                category="agentic",
                subject="db_direct",
                metadata={"subset": "db_bench", "sample_index": i},
            )
            for i in [3, 1, 2]
        ]
        episodes = list(ds.iter_episodes())
        assert len(episodes) == 1
        indices = [r.metadata["sample_index"] for r in episodes[0]]
        assert indices == [1, 2, 3]

    def test_multi_subset_episodes(self) -> None:
        ds = LifelongAgentDataset(subset="all")
        ds._records = [
            EvalRecord(
                record_id="lifelong-db-0",
                problem="task",
                reference="{}",
                category="agentic",
                subject="db_direct",
                metadata={"subset": "db_bench", "sample_index": 0},
            ),
            EvalRecord(
                record_id="lifelong-kg-0",
                problem="task",
                reference="{}",
                category="agentic",
                subject="knowledge_graph",
                metadata={"subset": "knowledge_graph", "sample_index": 0},
            ),
        ]
        episodes = list(ds.iter_episodes())
        assert len(episodes) == 2

    def test_episode_metadata_tags(self) -> None:
        ds = LifelongAgentDataset(subset="db_bench")
        ds._records = [
            EvalRecord(
                record_id=f"lifelong-db-{i}",
                problem="task",
                reference="{}",
                category="agentic",
                subject="db_direct",
                metadata={"subset": "db_bench", "sample_index": i},
            )
            for i in range(5)
        ]
        episodes = list(ds.iter_episodes())
        for record in episodes[0]:
            assert "episode_task_index" in record.metadata
            assert record.metadata["episode_length"] == 5


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------


class TestDataset:
    def test_instantiation_default(self) -> None:
        ds = LifelongAgentDataset()
        assert ds.dataset_id == "lifelong-agent"
        assert ds._subset == "all"

    def test_instantiation_specific_subset(self) -> None:
        ds = LifelongAgentDataset(subset="db_bench")
        assert ds._subset == "db_bench"

    def test_subset_validation(self) -> None:
        try:
            LifelongAgentDataset(subset="invalid")
            assert False, "Should have raised ValueError"
        except ValueError:
            pass

    def test_all_subsets_accepted(self) -> None:
        for s in ("db_bench", "knowledge_graph", "os_interaction", "all"):
            ds = LifelongAgentDataset(subset=s)
            assert ds._subset == s

    def test_has_create_task_env(self) -> None:
        """Dataset should provide create_task_env for multi-turn eval."""
        ds = LifelongAgentDataset()
        assert hasattr(ds, "create_task_env")


# ---------------------------------------------------------------------------
# Multi-turn environments
# ---------------------------------------------------------------------------


class TestDBEnvironment:
    def test_multi_turn_select(self) -> None:
        """DB environment should handle multi-turn SQL interaction."""
        from openjarvis.evals.environments.lifelong_agent_env import DBEnvironment

        record = _db_record(
            direct=[[1, "Alice", 95.5], [2, "Bob", 87.0], [3, "Carol", 92.3]],
        )
        env = DBEnvironment(use_mysql=False)
        obs = env.reset(record)
        assert "users" in obs
        assert "Alice" in obs

        # Turn 1: agent explores
        obs, done = env.step(
            "Action: Operation\n```sql\nSELECT COUNT(*) FROM users\n```"
        )
        assert not done
        assert "3" in obs or "Result" in obs

        # Turn 2: agent answers
        answer = (
            "Action: Answer\nFinal Answer: "
            "[(1, 'Alice', 95.5), (2, 'Bob', 87.0), "
            "(3, 'Carol', 92.3)]"
        )
        obs, done = env.step(answer)
        assert done

        # Evaluate
        ok, meta = env.evaluate()
        assert ok is True
        assert meta["match_type"] == "interactive_db_direct"
        env.close()

    def test_multi_turn_insert(self) -> None:
        """DB environment should handle DML tasks."""
        from openjarvis.evals.environments.lifelong_agent_env import DBEnvironment

        record = _db_record(
            md5="x",
            sql="INSERT INTO users VALUES (4, 'Dave', 88.0)",
        )
        env = DBEnvironment(use_mysql=False)
        env.reset(record)

        # Agent executes the correct INSERT
        obs, done = env.step(
            "Action: Operation\n```sql\nINSERT INTO users VALUES (4, 'Dave', 88.0)\n```"
        )
        assert not done
        assert "successfully" in obs.lower() or "Result" in obs

        # Agent signals done
        obs, done = env.step("Action: Answer\nFinal Answer: Done")
        assert done

        ok, meta = env.evaluate()
        assert ok is True
        env.close()

    def test_bad_sql_returns_error(self) -> None:
        from openjarvis.evals.environments.lifelong_agent_env import DBEnvironment

        record = _db_record(direct=[[1]])
        env = DBEnvironment(use_mysql=False)
        env.reset(record)

        obs, done = env.step("SELECT * FROM nonexistent_table")
        assert "Error" in obs or "error" in obs.lower()
        assert not done
        env.close()

    def test_unparseable_response(self) -> None:
        from openjarvis.evals.environments.lifelong_agent_env import DBEnvironment

        record = _db_record(direct=[[1]])
        env = DBEnvironment(use_mysql=False)
        env.reset(record)

        obs, done = env.step("I'm not sure what to do")
        assert "Error" in obs
        assert not done
        env.close()


class TestKGEnvironment:
    def test_multi_turn_with_oracle(self) -> None:
        """KG environment should simulate API calls from action_list."""
        from openjarvis.evals.environments.lifelong_agent_env import KGEnvironment

        # Use string action_list matching HF dataset format
        record = _kg_record(
            answer_list=["m.001"],
            action_list=[
                "get_relations(m.02h8b9t)",
                "get_neighbors(m.02h8b9t, music.genre)",
            ],
        )
        env = KGEnvironment()
        obs = env.reset(record)
        assert "Question" in obs

        # Turn 1: agent calls API — oracle infers relation from next action
        obs, done = env.step("Action: get_relations(m.02h8b9t)")
        assert not done
        assert "Result" in obs

        # Turn 2: agent calls another API
        obs, done = env.step("Action: get_neighbors(#0, music.genre)")
        assert not done

        # Turn 3: agent provides final answer
        obs, done = env.step("Final Answer: m.001")
        assert done

        ok, meta = env.evaluate()
        assert ok is True
        assert meta["f1"] == 1.0
        assert meta["exact_match"] is True
        env.close()

    def test_multi_turn_with_dict_oracle(self) -> None:
        """KG environment should also handle dict-format action_list."""
        from openjarvis.evals.environments.lifelong_agent_env import KGEnvironment

        record = _kg_record(
            answer_list=["m.001"],
            action_list=[
                {"result": "['music.genre', 'film.genre']"},
                {"result": "m.001"},
            ],
        )
        env = KGEnvironment()
        env.reset(record)
        obs, done = env.step("Action: get_relations(m.02h8b9t)")
        assert not done
        assert "music.genre" in obs
        obs, done = env.step("Action: get_neighbors(#0, music.genre)")
        assert not done
        env.step("Final Answer: m.001")
        ok, meta = env.evaluate()
        assert ok is True
        env.close()

    def test_wrong_answer(self) -> None:
        from openjarvis.evals.environments.lifelong_agent_env import KGEnvironment

        record = _kg_record(answer_list=["m.001"])
        env = KGEnvironment()
        env.reset(record)
        env.step("Final Answer: m.999")

        ok, meta = env.evaluate()
        assert ok is False
        assert meta["f1"] == 0.0
        env.close()

    def test_invalid_api_call(self) -> None:
        from openjarvis.evals.environments.lifelong_agent_env import KGEnvironment

        record = _kg_record(answer_list=["m.001"])
        env = KGEnvironment()
        env.reset(record)

        obs, done = env.step("Action: invalid_func(x)")
        assert "Error" in obs
        assert not done
        env.close()

    def test_partial_f1(self) -> None:
        from openjarvis.evals.environments.lifelong_agent_env import KGEnvironment

        record = _kg_record(answer_list=["m.001", "m.002"])
        env = KGEnvironment()
        env.reset(record)
        env.step("Final Answer: m.001")

        ok, meta = env.evaluate()
        assert ok is False  # not exact match
        assert meta["f1"] > 0  # but partial credit
        assert meta["precision"] == 1.0
        assert meta["recall"] == 0.5
        env.close()


class TestOSEnvironment:
    def test_requires_docker(self) -> None:
        """OS environment should fail loudly without Docker."""
        import shutil

        from openjarvis.evals.environments.lifelong_agent_env import OSEnvironment

        if shutil.which("docker"):
            # Docker is available — test that it at least initializes
            env = OSEnvironment()
            # Don't actually run the full test on CI
            env.close()
        else:
            env = OSEnvironment()
            try:
                env.reset(_os_record())
                assert False, "Should have raised RuntimeError"
            except RuntimeError as exc:
                assert "Docker" in str(exc)


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------


class TestCLI:
    def test_in_benchmarks(self) -> None:
        from openjarvis.evals.cli import BENCHMARKS

        assert "lifelong-agent" in BENCHMARKS
        assert BENCHMARKS["lifelong-agent"]["category"] == "agentic"

    def test_build_dataset(self) -> None:
        from openjarvis.evals.cli import _build_dataset

        ds = _build_dataset("lifelong-agent")
        assert ds.dataset_id == "lifelong-agent"
        assert hasattr(ds, "create_task_env")

    def test_build_scorer(self) -> None:
        from openjarvis.evals.cli import _build_scorer

        s = _build_scorer("lifelong-agent", None, "test-model")
        assert s.scorer_id == "lifelong-agent"


# ---------------------------------------------------------------------------
# Runner episode_mode integration
# ---------------------------------------------------------------------------


class TestRunnerEpisodeMode:
    def test_episode_mode_field_exists(self) -> None:
        from openjarvis.evals.core.types import RunConfig

        config = RunConfig(
            benchmark="lifelong-agent",
            backend="jarvis-direct",
            model="test",
            episode_mode=True,
        )
        assert config.episode_mode is True

    def test_runner_has_episode_mode_method(self) -> None:
        from openjarvis.evals.core.runner import EvalRunner

        assert hasattr(EvalRunner, "_run_episode_mode")
        assert hasattr(EvalRunner, "_process_interactive")
        assert hasattr(EvalRunner, "_inject_examples")

    def test_inject_examples_empty(self) -> None:
        """With no examples, record should be returned unchanged."""
        from openjarvis.evals.core.runner import EvalRunner

        record = EvalRecord(
            record_id="test",
            problem="What is 2+2?",
            reference="4",
            category="reasoning",
            subject="math",
            metadata={},
        )
        # Call the static-ish method
        runner = EvalRunner.__new__(EvalRunner)
        result = runner._inject_examples(record, [])
        assert result.problem == record.problem

    def test_inject_examples_adds_context(self) -> None:
        """With examples, record should have examples prepended."""
        from openjarvis.evals.core.runner import EvalRunner

        record = EvalRecord(
            record_id="test",
            problem="What is 2+2?",
            reference="4",
            category="reasoning",
            subject="math",
            metadata={},
        )
        examples = [{"problem": "What is 1+1?", "answer": "2"}]
        runner = EvalRunner.__new__(EvalRunner)
        result = runner._inject_examples(record, examples)
        assert "Previously Completed Tasks" in result.problem
        assert "What is 1+1?" in result.problem
        assert result.problem.endswith("What is 2+2?")

    def test_inject_examples_with_interaction_history(self) -> None:
        """With full interaction history, should include multi-turn exchanges."""
        from openjarvis.evals.core.runner import EvalRunner

        record = EvalRecord(
            record_id="test",
            problem="What is 3+3?",
            reference="6",
            category="reasoning",
            subject="math",
            metadata={},
        )
        examples = [
            {
                "problem": "What is 1+1?",
                "answer": "2",
                "interaction_history": [
                    {"role": "user", "content": "What is 1+1?"},
                    {"role": "assistant", "content": "Action: compute(1+1)"},
                    {"role": "user", "content": "Result: 2"},
                    {"role": "assistant", "content": "Final Answer: 2"},
                ],
            }
        ]
        runner = EvalRunner.__new__(EvalRunner)
        result = runner._inject_examples(record, examples)
        assert "Previously Completed Tasks" in result.problem
        assert "Action: compute(1+1)" in result.problem
        assert "Result: 2" in result.problem
        assert result.problem.endswith("What is 3+3?")

    def test_max_prior_examples_constant(self) -> None:
        """Runner should have a FIFO buffer size matching original default."""
        from openjarvis.evals.core.runner import EvalRunner

        assert EvalRunner._MAX_PRIOR_EXAMPLES == 3


# ---------------------------------------------------------------------------
# KG variable reference resolution
# ---------------------------------------------------------------------------


class TestKGVariableReference:
    def test_variable_ref_in_scorer(self) -> None:
        """Scorer should handle Final Answer: #N format."""
        # When a variable ref is given and entity IDs are elsewhere in text
        result = extract_kg_answers(
            "I found the answer.\nThe entity m.02h8b9t matches.\nFinal Answer: #2"
        )
        assert "m.02h8b9t" in result

    def test_variable_ref_no_entities(self) -> None:
        """Variable ref with no entity IDs should return the ref."""
        result = extract_kg_answers("Final Answer: #3")
        assert result == ["#_3"]

    def test_variable_ref_in_env(self) -> None:
        """KG environment should resolve variable references."""
        from openjarvis.evals.environments.lifelong_agent_env import KGEnvironment

        record = _kg_record(
            answer_list=["m.001"],
            action_list=[
                "get_relations(m.02h8b9t)",
                "get_neighbors(m.02h8b9t, music.genre)",
            ],
        )
        env = KGEnvironment()
        env.reset(record)

        # Agent calls APIs, building up variables
        env.step("Action: get_relations(m.02h8b9t)")
        env.step("Action: get_neighbors(m.02h8b9t, music.genre)")

        # Agent provides final answer as variable reference
        obs, done = env.step("Final Answer: #3")
        assert done

        env.close()

    def test_variable_ref_with_var_keyword(self) -> None:
        """Should handle 'Final Answer: Variable #2' format."""
        result = extract_kg_answers(
            "Based on my analysis, m.001 is the answer.\nFinal Answer: Variable #2"
        )
        assert "m.001" in result


# ---------------------------------------------------------------------------
# OS action format
# ---------------------------------------------------------------------------


class TestOSActionFormat:
    def test_original_format_act_bash(self) -> None:
        """Should parse original format: Act: bash\\n```bash\\n...\\n```"""
        cmds = _extract_bash_commands("Act: bash\n```bash\nls -la /tmp\n```")
        assert len(cmds) == 1
        assert "ls -la" in cmds[0]

    def test_original_format_multiple(self) -> None:
        """Should parse multiple Act: bash blocks."""
        text = (
            "Act: bash\n```bash\nmkdir /tmp/test\n```\n"
            "Act: bash\n```bash\ntouch /tmp/test/file.txt\n```"
        )
        cmds = _extract_bash_commands(text)
        assert len(cmds) == 2


# ---------------------------------------------------------------------------
# Per-subset max turns
# ---------------------------------------------------------------------------


class TestMaxTurns:
    def test_db_max_turns(self) -> None:
        from openjarvis.evals.environments.lifelong_agent_env import (
            MAX_TURNS_DB,
            DBEnvironment,
        )

        env = DBEnvironment(use_mysql=False)
        assert env.max_turns == MAX_TURNS_DB
        assert env.max_turns == 3

    def test_kg_max_turns(self) -> None:
        from openjarvis.evals.environments.lifelong_agent_env import (
            MAX_TURNS_KG,
            KGEnvironment,
        )

        env = KGEnvironment()
        assert env.max_turns == MAX_TURNS_KG
        assert env.max_turns == 15

    def test_os_max_turns(self) -> None:
        from openjarvis.evals.environments.lifelong_agent_env import (
            MAX_TURNS_OS,
            OSEnvironment,
        )

        env = OSEnvironment()
        assert env.max_turns == MAX_TURNS_OS
        assert env.max_turns == 5

    def test_base_default(self) -> None:
        from openjarvis.evals.environments.base import TaskEnvironment

        # Can't instantiate ABC, but verify the property exists
        assert hasattr(TaskEnvironment, "max_turns")


# ---------------------------------------------------------------------------
# Numeric tolerance
# ---------------------------------------------------------------------------


class TestNumericTolerance:
    def test_abs_tol_near_zero(self) -> None:
        """abs_tol=1e-6 should make very small values match zero."""
        assert values_match(0, 1e-7)
        assert values_match(0.0, 5e-7)

    def test_abs_tol_just_outside(self) -> None:
        """Values beyond abs_tol should not match."""
        assert not values_match(0, 1e-5)

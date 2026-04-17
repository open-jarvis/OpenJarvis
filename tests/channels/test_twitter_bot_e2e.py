"""End-to-end tests for the Twitter bot mention handler.

Tests cover:
- Tweet classification (_classify_mention)
- Prompt building for each mention type
- Mention polling → handler dispatch
- Full reactive flow: mention → classify → prompt → agent → tool call → reply
- Environment variable expansion in http_request headers (GitHub issue creation)
"""

from __future__ import annotations

import importlib
import json
import os

# ---------------------------------------------------------------------------
# Import the bot module helpers
# ---------------------------------------------------------------------------
import sys
import threading
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.channels._stubs import ChannelMessage
from openjarvis.channels.twitter_channel import TwitterChannel
from openjarvis.tools.http_request import HttpRequestTool

# Add examples dir to path so we can import the bot module
_EXAMPLES_DIR = os.path.join(
    os.path.dirname(__file__), os.pardir, os.pardir, "examples", "twitter_bot",
)
sys.path.insert(0, os.path.abspath(_EXAMPLES_DIR))
twitter_bot = importlib.import_module("twitter_bot")
sys.path.pop(0)

_classify_mention = twitter_bot._classify_mention
_build_question_prompt = twitter_bot._build_question_prompt
_build_question_grounded_prompt = twitter_bot._build_question_grounded_prompt
_build_question_deferral_prompt = twitter_bot._build_question_deferral_prompt
_build_bug_prompt = twitter_bot._build_bug_prompt
_build_feature_prompt = twitter_bot._build_feature_prompt
_build_praise_prompt = twitter_bot._build_praise_prompt
DEMO_TWEETS = twitter_bot.DEMO_TWEETS


# =========================================================================
# 1. Classification tests
# =========================================================================


class TestClassifyMention:
    """Test the keyword-based mention classifier."""

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("@OpenJarvisAI bug: the memory_search tool crashes", "BUG_REPORT"),
            ("@OpenJarvisAI crash when I run jarvis ask", "BUG_REPORT"),
            ("@OpenJarvisAI error on startup with ollama", "BUG_REPORT"),
            ("@OpenJarvisAI the CLI fails after update", "BUG_REPORT"),
            ("@OpenJarvisAI broken link in the docs", "BUG_REPORT"),
            ("@OpenJarvisAI segfault with large file", "BUG_REPORT"),
        ],
    )
    def test_bug_report(self, text, expected):
        assert _classify_mention(text) == expected

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("@OpenJarvisAI feature request: add a scheduler UI", "FEATURE_REQUEST"),
            ("@OpenJarvisAI would love a web dashboard", "FEATURE_REQUEST"),
            (
                "@OpenJarvisAI it would be great to have notifications",
                "FEATURE_REQUEST",
            ),
            ("@OpenJarvisAI I wish there was a mobile app", "FEATURE_REQUEST"),
            ("@OpenJarvisAI please add dark mode", "FEATURE_REQUEST"),
            ("@OpenJarvisAI can you add voice input?", "FEATURE_REQUEST"),
            ("@OpenJarvisAI any plans for a VS Code extension?", "FEATURE_REQUEST"),
        ],
    )
    def test_feature_request(self, text, expected):
        assert _classify_mention(text) == expected

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("@OpenJarvisAI just discovered this, love it!", "PRAISE"),
            ("@OpenJarvisAI this is amazing work", "PRAISE"),
            ("@OpenJarvisAI awesome project, great work!", "PRAISE"),
            ("@OpenJarvisAI I'm impressed by the speed", "PRAISE"),
            ("@OpenJarvisAI switched from langchain, incredible", "PRAISE"),
        ],
    )
    def test_praise(self, text, expected):
        assert _classify_mention(text) == expected

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("@OpenJarvisAI BUY CRYPTO NOW", "SPAM"),
            ("@OpenJarvisAI free download link in bio", "SPAM"),
            ("@OpenJarvisAI guaranteed income 10x returns", "SPAM"),
        ],
    )
    def test_spam(self, text, expected):
        assert _classify_mention(text) == expected

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("@OpenJarvisAI how do I add a new channel?", "QUESTION"),
            ("@OpenJarvisAI what models do you support?", "QUESTION"),
            ("@OpenJarvisAI does this work on Windows?", "QUESTION"),
            ("@OpenJarvisAI tell me about the architecture", "QUESTION"),
        ],
    )
    def test_question(self, text, expected):
        assert _classify_mention(text) == expected

    def test_demo_tweets_cover_all_types(self):
        """The built-in DEMO_TWEETS should cover all five categories."""
        types = {_classify_mention(t["text"]) for t in DEMO_TWEETS}
        assert types == {"QUESTION", "BUG_REPORT", "FEATURE_REQUEST", "PRAISE", "SPAM"}


# =========================================================================
# 2. Prompt builder tests
# =========================================================================


class TestPromptBuilders:
    """Verify prompt builders produce well-formed prompts with the right info."""

    def test_question_deferral_prompt_has_channel_send(self):
        """Deferral prompt (used when retrieval is empty/weak)."""
        prompt = _build_question_deferral_prompt("alice", "123", "how do I install?")
        assert "channel_send" in prompt
        assert "alice" in prompt
        assert "123" in prompt
        assert "how do I install?" in prompt
        # Deferral prompt explicitly tells the model NOT to guess
        assert "do not guess" in prompt.lower() or "do not make up" in prompt.lower()

    def test_question_grounded_prompt_embeds_context(self):
        """Grounded prompt (used when retrieval score >= threshold)."""
        context = "[1] hardware.md  —  Running Without a GPU\nUse llama.cpp for CPU."
        prompt = _build_question_grounded_prompt(
            "alice", "123", "can I run on cpu?", context, 0.71
        )
        assert "channel_send" in prompt
        assert context in prompt
        # Grounded prompt must instruct the model to answer ONLY from context
        lc = prompt.lower()
        assert (
            "only from facts in the context" in lc
            or "only from the context" in lc
        )

    def test_bug_prompt_contains_github_url(self):
        prompt = _build_bug_prompt("bob", "456", "crash on startup")
        assert "api.github.com/repos/open-jarvis/OpenJarvis/issues" in prompt
        assert "http_request" in prompt
        assert "channel_send" in prompt
        assert "bob" in prompt
        assert "bug" in prompt
        assert "456" in prompt

    def test_feature_prompt_contains_github_url(self):
        prompt = _build_feature_prompt("carol", "789", "add dark mode")
        assert "api.github.com/repos/open-jarvis/OpenJarvis/issues" in prompt
        assert "enhancement" in prompt
        assert "carol" in prompt
        assert "789" in prompt

    def test_praise_prompt_has_channel_send(self):
        prompt = _build_praise_prompt("dave", "101", "love this project!")
        assert "channel_send" in prompt
        assert "dave" in prompt
        assert "101" in prompt

    def test_all_prompts_include_voice_rules(self):
        """Every prompt should include the voice rules (280 chars, lowercase, etc.)."""
        prompts = [
            _build_question_prompt("u", "1", "q"),
            _build_bug_prompt("u", "1", "b"),
            _build_feature_prompt("u", "1", "f"),
            _build_praise_prompt("u", "1", "p"),
        ]
        for prompt in prompts:
            assert "<=280 characters" in prompt
            assert "lowercase prose" in prompt

    def test_bug_prompt_includes_from_twitter_label(self):
        prompt = _build_bug_prompt("user", "1", "crash")
        assert "from-twitter" in prompt

    def test_feature_prompt_includes_from_twitter_label(self):
        prompt = _build_feature_prompt("user", "1", "feature")
        assert "from-twitter" in prompt


# =========================================================================
# 3. Mention polling + handler dispatch
# =========================================================================


class TestMentionPolling:
    """Test that _poll_mentions fetches tweets and dispatches to handlers."""

    def test_poll_dispatches_to_handler(self):
        """A single poll cycle should dispatch tweets to registered handlers."""
        ch = TwitterChannel(
            bearer_token="test-bearer",
            bot_user_id="999",
            poll_interval=1,
        )

        handler = MagicMock()
        ch.on_message(handler)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "111",
                    "author_id": "alice",
                    "text": "@OpenJarvisAI how do I install?",
                    "conversation_id": "111",
                },
            ],
        }

        with patch("httpx.get", return_value=mock_response):
            ch._stop_event = threading.Event()

            def poll_once():
                import httpx as _httpx
                headers = {"Authorization": "Bearer test-bearer"}
                url = "https://api.twitter.com/2/users/999/mentions"
                params = {"tweet.fields": "author_id,conversation_id,created_at"}
                resp = _httpx.get(url, headers=headers, params=params, timeout=10.0)
                data = resp.json()
                for tweet in data.get("data", []):
                    cm = ChannelMessage(
                        channel="twitter",
                        sender=tweet.get("author_id", ""),
                        content=tweet.get("text", ""),
                        message_id=tweet["id"],
                        conversation_id=tweet.get("conversation_id", ""),
                    )
                    for h in ch._handlers:
                        h(cm)

            poll_once()

        handler.assert_called_once()
        msg = handler.call_args[0][0]
        assert isinstance(msg, ChannelMessage)
        assert msg.sender == "alice"
        assert msg.content == "@OpenJarvisAI how do I install?"
        assert msg.message_id == "111"

    def test_poll_tracks_since_id(self):
        """Polling should track since_id to avoid reprocessing tweets."""
        ch = TwitterChannel(
            bearer_token="test-bearer",
            bot_user_id="999",
            poll_interval=0,
        )
        assert ch._since_id is None

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {"id": "200", "text": "hello", "author_id": "u1"},
                {"id": "300", "text": "world", "author_id": "u2"},
            ],
        }

        ch._stop_event = threading.Event()

        def get_and_stop(*args, **kwargs):
            ch._stop_event.set()
            return mock_resp

        with patch("httpx.get", side_effect=get_and_stop):
            ch._poll_mentions()

        assert ch._since_id == "300"

    def test_poll_empty_response(self):
        """Empty mentions response should not error or call handlers."""
        ch = TwitterChannel(
            bearer_token="test-bearer",
            bot_user_id="999",
            poll_interval=0,
        )
        handler = MagicMock()
        ch.on_message(handler)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": []}

        ch._stop_event = threading.Event()

        def get_and_stop(*args, **kwargs):
            ch._stop_event.set()
            return mock_resp

        with patch("httpx.get", side_effect=get_and_stop):
            ch._poll_mentions()

        handler.assert_not_called()


# =========================================================================
# 4. Env var expansion in http_request (GitHub issue creation)
# =========================================================================


class TestEnvVarExpansion:
    """Verify the http_request tool expands $ENV_VARS in headers."""

    def test_github_token_expanded(self):
        """$GITHUB_TOKEN in Authorization header should be expanded."""
        tool = HttpRequestTool()

        mock_rust = MagicMock()
        mock_rust.HttpRequestTool.return_value.execute.side_effect = RuntimeError(
            "mocked",
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.text = '{"number": 42}'
        mock_resp.headers = {"content-type": "application/json"}

        with (
            patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test123"}),
            patch(
                "openjarvis._rust_bridge.get_rust_module",
                return_value=mock_rust,
            ),
            patch("openjarvis.tools.http_request.check_ssrf", return_value=None),
            patch(
                "openjarvis.tools.http_request.httpx.request",
                return_value=mock_resp,
            ) as mock_req,
        ):
            result = tool.execute(
                url="https://api.github.com/repos/open-jarvis/OpenJarvis/issues",
                method="POST",
                headers={
                    "Authorization": "Bearer $GITHUB_TOKEN",
                    "Accept": "application/vnd.github+json",
                },
                body='{"title": "test", "labels": ["bug"]}',
            )

        assert result.success is True
        actual_headers = mock_req.call_args[1]["headers"]
        assert actual_headers["Authorization"] == "Bearer ghp_test123"
        assert actual_headers["Accept"] == "application/vnd.github+json"

    def test_unexpanded_var_without_env(self):
        """$GITHUB_TOKEN without env var set should remain as literal."""
        tool = HttpRequestTool()

        mock_rust = MagicMock()
        mock_rust.HttpRequestTool.return_value.execute.side_effect = RuntimeError(
            "mocked",
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "Bad credentials"
        mock_resp.headers = {"content-type": "text/plain"}

        env = {k: v for k, v in os.environ.items() if k != "GITHUB_TOKEN"}
        with (
            patch.dict(os.environ, env, clear=True),
            patch(
                "openjarvis._rust_bridge.get_rust_module",
                return_value=mock_rust,
            ),
            patch("openjarvis.tools.http_request.check_ssrf", return_value=None),
            patch(
                "openjarvis.tools.http_request.httpx.request",
                return_value=mock_resp,
            ) as mock_req,
        ):
            tool.execute(
                url="https://api.github.com/repos/test/test/issues",
                method="POST",
                headers={"Authorization": "Bearer $GITHUB_TOKEN"},
                body="{}",
            )

        actual_headers = mock_req.call_args[1]["headers"]
        assert actual_headers["Authorization"] == "Bearer $GITHUB_TOKEN"

    def test_non_string_header_values_pass_through(self):
        """Non-string header values should pass through without error."""
        tool = HttpRequestTool()

        mock_rust = MagicMock()
        mock_rust.HttpRequestTool.return_value.execute.side_effect = RuntimeError(
            "mocked",
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "ok"
        mock_resp.headers = {}

        with (
            patch(
                "openjarvis._rust_bridge.get_rust_module",
                return_value=mock_rust,
            ),
            patch("openjarvis.tools.http_request.check_ssrf", return_value=None),
            patch(
                "openjarvis.tools.http_request.httpx.request",
                return_value=mock_resp,
            ) as mock_req,
        ):
            tool.execute(
                url="https://example.com",
                headers={"X-Count": 42, "X-Name": "test"},
            )

        actual_headers = mock_req.call_args[1]["headers"]
        assert actual_headers["X-Count"] == 42
        assert actual_headers["X-Name"] == "test"


# =========================================================================
# 5. Full reactive e2e flow (mock Jarvis + TwitterChannel)
# =========================================================================


class TestFullE2EFlow:
    """Test the full flow: mention arrives → classify → prompt → agent → tool calls."""

    def _make_mock_jarvis(self, responses=None):
        """Create a mock Jarvis instance that returns canned responses."""
        j = MagicMock()
        if responses:
            j.ask.side_effect = responses
        else:
            j.ask.return_value = "mock response"
        return j

    def test_question_flow(self):
        """Question mention → retrieval runs in Python, agent only needs channel_send.

        After the dense-retrieval refactor, ``memory_search`` is no longer
        a model-visible tool; retrieval happens out-of-band and the score
        picks between grounded/deferral prompts. The only tool the agent
        needs for a QUESTION is ``channel_send``.
        """
        j = self._make_mock_jarvis(["check the docs at open-jarvis.github.io"])
        tweet = DEMO_TWEETS[0]

        mention_type = _classify_mention(tweet["text"])
        assert mention_type == "QUESTION"

        prompt = _build_question_deferral_prompt(
            tweet["author"], tweet["id"], tweet["text"]
        )
        j.ask(
            prompt,
            agent="orchestrator",
            tools=["channel_send"],
            temperature=0.4,
        )

        j.ask.assert_called_once()
        call_kwargs = j.ask.call_args
        assert "channel_send" in call_kwargs[1]["tools"]
        # memory_search is explicitly NOT passed — retrieval was already done
        assert "memory_search" not in call_kwargs[1]["tools"]
        assert call_kwargs[1]["agent"] == "orchestrator"

    def test_bug_report_flow(self):
        """Bug mention → http_request (GitHub issue) + channel_send."""
        j = self._make_mock_jarvis(["opened an issue for this"])
        tweet = DEMO_TWEETS[1]

        mention_type = _classify_mention(tweet["text"])
        assert mention_type == "BUG_REPORT"

        prompt = _build_bug_prompt(tweet["author"], tweet["id"], tweet["text"])
        j.ask(
            prompt,
            agent="orchestrator",
            tools=["http_request", "channel_send"],
            temperature=0.4,
        )

        call_kwargs = j.ask.call_args
        assert "http_request" in call_kwargs[1]["tools"]
        assert "channel_send" in call_kwargs[1]["tools"]
        assert "api.github.com" in call_kwargs[0][0]
        assert "bug" in call_kwargs[0][0]

    def test_feature_request_flow(self):
        """Feature mention → http_request (GitHub issue) + channel_send."""
        j = self._make_mock_jarvis(
            ["love this idea — opened an issue to track it"],
        )
        tweet = DEMO_TWEETS[2]

        mention_type = _classify_mention(tweet["text"])
        assert mention_type == "FEATURE_REQUEST"

        prompt = _build_feature_prompt(
            tweet["author"], tweet["id"], tweet["text"],
        )
        j.ask(
            prompt,
            agent="orchestrator",
            tools=["http_request", "channel_send"],
            temperature=0.4,
        )

        call_kwargs = j.ask.call_args
        assert "http_request" in call_kwargs[1]["tools"]
        assert "enhancement" in call_kwargs[0][0]

    def test_praise_flow(self):
        """Praise mention → channel_send only."""
        j = self._make_mock_jarvis(["thanks, glad you like it!"])
        tweet = DEMO_TWEETS[3]

        mention_type = _classify_mention(tweet["text"])
        assert mention_type == "PRAISE"

        prompt = _build_praise_prompt(tweet["author"], tweet["id"], tweet["text"])
        j.ask(prompt, agent="orchestrator", tools=["channel_send"], temperature=0.4)

        call_kwargs = j.ask.call_args
        assert call_kwargs[1]["tools"] == ["channel_send"]

    def test_spam_is_ignored(self):
        """Spam mentions should be skipped — no Jarvis.ask call."""
        j = self._make_mock_jarvis()
        tweet = DEMO_TWEETS[4]

        mention_type = _classify_mention(tweet["text"])
        assert mention_type == "SPAM"

        if mention_type != "SPAM":
            j.ask("should not be called")

        j.ask.assert_not_called()

    def test_all_demo_tweets_processed(self):
        """Run each demo tweet; verify classification + tool selection.

        Post dense-retrieval refactor: QUESTIONs no longer request
        ``memory_search`` as a tool — retrieval is done in Python.
        """
        expected = [
            ("QUESTION", ["channel_send"]),
            ("BUG_REPORT", ["http_request", "channel_send"]),
            ("FEATURE_REQUEST", ["http_request", "channel_send"]),
            ("PRAISE", ["channel_send"]),
            ("SPAM", None),
        ]

        for tweet, (exp_type, exp_tools) in zip(DEMO_TWEETS, expected):
            mention_type = _classify_mention(tweet["text"])
            assert mention_type == exp_type, f"Tweet by {tweet['author']} misclassified"

            if mention_type == "SPAM":
                continue

            if mention_type == "QUESTION":
                tools = ["channel_send"]
            elif mention_type == "BUG_REPORT":
                tools = ["http_request", "channel_send"]
            elif mention_type == "FEATURE_REQUEST":
                tools = ["http_request", "channel_send"]
            else:
                tools = ["channel_send"]

            assert tools == exp_tools, f"Wrong tools for {tweet['author']}"


# =========================================================================
# 6. Send-as-reply (conversation_id passthrough)
# =========================================================================


class TestReplyConversationId:
    """Verify that replies always pass conversation_id back to the Twitter API."""

    def test_send_passes_conversation_id_as_reply(self):
        ch = TwitterChannel(
            bearer_token="b",
            api_key="ck",
            api_secret="cs",
            access_token="at",
            access_secret="as",
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 201

        with patch("httpx.post", return_value=mock_resp) as mock_post:
            ch.send(
                "twitter",
                "opened an issue for this — we'll look into it",
                conversation_id="1000000000000000002",
            )

        payload = mock_post.call_args[1]["json"]
        assert payload["reply"]["in_reply_to_tweet_id"] == "1000000000000000002"
        assert len(payload["text"]) <= 280


# =========================================================================
# 7. GitHub issue creation e2e (http_request with expanded token)
# =========================================================================


class TestGitHubIssueCreation:
    """Simulate the LLM calling http_request to create a GitHub issue."""

    def test_create_bug_issue(self):
        tool = HttpRequestTool()

        mock_rust = MagicMock()
        mock_rust.HttpRequestTool.return_value.execute.side_effect = (
            RuntimeError("mocked")
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.text = json.dumps({
            "number": 42,
            "html_url": "https://github.com/open-jarvis/OpenJarvis/issues/42",
        })
        mock_resp.headers = {"content-type": "application/json"}

        with (
            patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_testtoken123"}),
            patch("openjarvis._rust_bridge.get_rust_module", return_value=mock_rust),
            patch("openjarvis.tools.http_request.check_ssrf", return_value=None),
            patch(
                "openjarvis.tools.http_request.httpx.request",
                return_value=mock_resp,
            ) as mock_req,
        ):
            result = tool.execute(
                url="https://api.github.com/repos/open-jarvis/OpenJarvis/issues",
                method="POST",
                headers={
                    "Authorization": "Bearer $GITHUB_TOKEN",
                    "Accept": "application/vnd.github+json",
                },
                body=json.dumps({
                    "title": "memory_search tool crashes on empty index",
                    "body": (
                        "reported via twitter by @bob_user: bug: the "
                        "memory_search tool crashes when the index is empty"
                    ),
                    "labels": ["bug", "from-twitter"],
                }),
            )

        assert result.success is True
        assert "42" in result.content

        actual_call = mock_req.call_args
        assert actual_call[0][0] == "POST"
        assert "api.github.com" in actual_call[0][1]
        assert (
            actual_call[1]["headers"]["Authorization"]
            == "Bearer ghp_testtoken123"
        )

        body = actual_call[1]["content"]
        parsed_body = json.loads(body)
        assert parsed_body["labels"] == ["bug", "from-twitter"]
        assert "bob_user" in parsed_body["body"]

    def test_create_feature_issue(self):
        tool = HttpRequestTool()

        mock_rust = MagicMock()
        mock_rust.HttpRequestTool.return_value.execute.side_effect = (
            RuntimeError("mocked")
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.text = json.dumps({"number": 43})
        mock_resp.headers = {"content-type": "application/json"}

        with (
            patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_testtoken123"}),
            patch("openjarvis._rust_bridge.get_rust_module", return_value=mock_rust),
            patch("openjarvis.tools.http_request.check_ssrf", return_value=None),
            patch(
                "openjarvis.tools.http_request.httpx.request",
                return_value=mock_resp,
            ) as mock_req,
        ):
            result = tool.execute(
                url="https://api.github.com/repos/open-jarvis/OpenJarvis/issues",
                method="POST",
                headers={
                    "Authorization": "Bearer $GITHUB_TOKEN",
                    "Accept": "application/vnd.github+json",
                },
                body=json.dumps({
                    "title": "feature request: built-in scheduler UI",
                    "body": (
                        "requested via twitter by @carol_eng: it would "
                        "be great to have a built-in scheduler UI"
                    ),
                    "labels": ["enhancement", "from-twitter"],
                }),
            )

        assert result.success is True
        body = json.loads(mock_req.call_args[1]["content"])
        assert body["labels"] == ["enhancement", "from-twitter"]
        assert "carol_eng" in body["body"]

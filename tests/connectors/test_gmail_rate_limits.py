"""Gmail uses HTTP 403 as well as 429 for transient quota limits."""

from unittest.mock import patch

import httpx
import pytest

from openjarvis.connectors import gmail


def _response(status, reason=None):
    payload = (
        {"messages": []}
        if reason is None
        else {"error": {"errors": [{"reason": reason}]}}
    )
    return httpx.Response(
        status,
        json=payload,
        request=httpx.Request(
            "GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages"
        ),
    )


@pytest.mark.parametrize("operation", ["list", "get"])
@pytest.mark.parametrize(
    "status,reason",
    [(403, "rateLimitExceeded"), (403, "userRateLimitExceeded"), (429, None)],
)
def test_quota_failure_retries_read_request(operation, status, reason):
    with (
        patch.object(
            gmail.httpx, "get", side_effect=[_response(status, reason), _response(200)]
        ) as get,
        patch("time.sleep") as sleep,
    ):
        if operation == "list":
            gmail._gmail_api_list_messages("test-token")
        else:
            gmail._gmail_api_get_message("test-token", "message1")

    assert get.call_count == 2
    sleep.assert_called_once()
    assert 1 <= sleep.call_args.args[0] <= 60


@pytest.mark.parametrize(
    "status,reason",
    [(401, "authError"), (403, "insufficientPermissions"), (403, "dailyLimitExceeded")],
)
def test_non_rate_failure_is_not_retried(status, reason):
    with (
        patch.object(gmail.httpx, "get", return_value=_response(status, reason)) as get,
        patch("time.sleep") as sleep,
    ):
        with pytest.raises(httpx.HTTPStatusError):
            gmail._gmail_api_list_messages("test-token")

    assert get.call_count == 1
    sleep.assert_not_called()


def test_retry_budget_exhaustion_exposes_quota_cause():
    with (
        patch.object(
            gmail.httpx, "get", return_value=_response(403, "rateLimitExceeded")
        ) as get,
        patch("time.sleep") as sleep,
    ):
        with pytest.raises(httpx.HTTPStatusError, match="[Rr]ate limited"):
            gmail._gmail_api_list_messages("test-token")

    assert get.call_count == 6
    assert sleep.call_count == 5

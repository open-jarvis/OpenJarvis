"""URL parsing must preserve the local/remote inference boundary."""

import socket

import pytest

from openjarvis.core._network import endpoint_is_local_network, endpoint_is_loopback


@pytest.mark.parametrize(
    "host",
    [
        "http://localhost:8000",
        "HTTP://LOCALHOST.:8000",
        "127.0.0.2:8000",
        "http://[::1]:8000",
        "http://[::ffff:127.0.0.1]:8000",
        "::1",
        "http://0.0.0.0:8000",
    ],
)
def test_loopback(host):
    assert endpoint_is_loopback(host)
    assert endpoint_is_local_network(host)


@pytest.mark.parametrize(
    "host",
    [
        "http://nim.local:8000",
        "http://192.168.1.5:8000",
        "http://10.1.2.3",
        "http://172.31.4.5",
        "http://[fd00::123]:8000",
    ],
)
def test_lan_is_self_hosted_but_not_on_this_device(host):
    assert endpoint_is_local_network(host)
    assert not endpoint_is_loopback(host)


@pytest.mark.parametrize(
    "host",
    [
        "https://api.example.com?@localhost",
        "https://api.example.com#@127.0.0.1",
        "https://user:password@api.example.com",
        "http://localhost.example.com",
        "http://127.0.0.1.example.com",
        "http://172.32.0.1",
        "http://[2001:4860::1]",
        "http://169.254.169.254",
        "http://100.64.0.1",
        "http://localhost:bad",
        "http://localhost:65536",
        "http://[::1]bad",
        "http://localhost..",
        "http://localhost\n.example.com",
        "",
        None,
        "file://localhost/private",
        "\x00http://localhost",
        "http://localhost\x7f",
    ],
)
def test_remote_or_invalid_is_not_misclassified(host):
    assert not endpoint_is_loopback(host)
    assert not endpoint_is_local_network(host)


def test_classification_never_resolves_a_host(monkeypatch):
    def no_dns(*args, **kwargs):
        raise AssertionError("classification performed a DNS lookup")

    monkeypatch.setattr(socket, "getaddrinfo", no_dns)
    assert endpoint_is_local_network("http://nim.local")
    assert not endpoint_is_loopback("https://api.example.com")

"""Espera del motor de inferencia al arrancar ``jarvis serve``.

Al iniciar sesión en Windows, la tarea programada puede lanzar el servidor
antes de que Ollama termine de arrancar. Con ``server.engine_wait_seconds``
el servidor reintenta durante ese plazo en vez de salir de inmediato.
"""

from __future__ import annotations

from openjarvis.cli.serve import _resolve_engine_with_wait


class FakeClock:
    """Reloj controlado: dormir solo avanza el tiempo, sin esperar de verdad."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _resolver(results):
    """Devuelve los resultados en orden, uno por llamada."""
    calls = iter(results)
    counter = {"calls": 0}

    def resolve():
        counter["calls"] += 1
        return next(calls)

    return resolve, counter


def test_returns_immediately_when_engine_is_ready():
    clock = FakeClock()
    resolve, counter = _resolver([("ollama", "engine")])

    result = _resolve_engine_with_wait(
        resolve, wait_seconds=60, sleep=clock.sleep, monotonic=clock.monotonic
    )

    assert result == ("ollama", "engine")
    assert counter["calls"] == 1
    assert clock.sleeps == []


def test_retries_until_engine_appears():
    clock = FakeClock()
    resolve, counter = _resolver([None, None, ("ollama", "engine")])

    result = _resolve_engine_with_wait(
        resolve,
        wait_seconds=60,
        poll_seconds=5,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )

    assert result == ("ollama", "engine")
    assert counter["calls"] == 3
    assert clock.sleeps == [5, 5]


def test_gives_up_after_the_wait():
    clock = FakeClock()
    resolve, counter = _resolver([None] * 100)

    result = _resolve_engine_with_wait(
        resolve,
        wait_seconds=12,
        poll_seconds=5,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )

    assert result is None
    # Intentos en t=0, 5, 10 y uno final al cumplirse el plazo (t=12).
    assert counter["calls"] == 4
    assert sum(clock.sleeps) == 12


def test_zero_wait_keeps_the_original_single_attempt():
    clock = FakeClock()
    resolve, counter = _resolver([None])

    result = _resolve_engine_with_wait(
        resolve, wait_seconds=0, sleep=clock.sleep, monotonic=clock.monotonic
    )

    assert result is None
    assert counter["calls"] == 1
    assert clock.sleeps == []


def test_server_config_defaults_to_no_wait():
    from openjarvis.core.config import ServerConfig

    assert ServerConfig().engine_wait_seconds == 0

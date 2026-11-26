"""Tests for openjarvis_rust agent constructors and host configuration (#1174)."""

from __future__ import annotations

import pytest


def test_rust_agent_classes_construct_without_panic():
    """Verify that all 5 Rust agent classes construct without Tokio reactor panic."""
    openjarvis_rust = pytest.importorskip("openjarvis_rust")

    classes = [
        ("SimpleAgent", "simple", False),
        ("OrchestratorAgent", "orchestrator", True),
        ("NativeReActAgent", "native_react", True),
        ("NativeOpenHandsAgent", "native_openhands", True),
        ("MonitorOperativeAgent", "monitor_operative", True),
    ]

    for class_name, expected_id, expected_tools in classes:
        cls = getattr(openjarvis_rust, class_name)
        agent = cls()
        assert agent.agent_id() == expected_id
        assert agent.accepts_tools() is expected_tools


def test_rust_agent_classes_accept_custom_host_and_engine():
    """Verify that agent constructors accept explicit host and engine configurations."""
    openjarvis_rust = pytest.importorskip("openjarvis_rust")

    custom_host = "http://127.0.0.1:9999"

    # Default engine (ollama) with custom host
    simple = openjarvis_rust.SimpleAgent(
        host=custom_host,
        model="custom-model",
        temperature=0.5,
    )
    assert simple.agent_id() == "simple"

    orch = openjarvis_rust.OrchestratorAgent(
        engine_key="vllm",
        host="http://127.0.0.1:8000",
        model="vllm-model",
        max_turns=5,
    )
    assert orch.agent_id() == "orchestrator"

    react = openjarvis_rust.NativeReActAgent(
        engine_key="sglang",
        host="http://127.0.0.1:30000",
        model="sglang-model",
        max_turns=8,
    )
    assert react.agent_id() == "native_react"

    openhands = openjarvis_rust.NativeOpenHandsAgent(
        engine_key="llamacpp",
        host="http://127.0.0.1:8080",
        model="llama-model",
        max_turns=6,
    )
    assert openhands.agent_id() == "native_openhands"

    monitor = openjarvis_rust.MonitorOperativeAgent(
        engine_key="mlx",
        host="http://127.0.0.1:8080",
        model="mlx-model",
        max_turns=4,
        memory_extraction="scratchpad",
        observation_compression="truncate",
        retrieval_strategy="keyword",
        task_decomposition="monolithic",
    )
    assert monitor.agent_id() == "monitor_operative"


def test_rust_agent_invalid_engine_raises_runtime_error():
    """Verify that unsupported engine_key returns an error rather than crashing."""
    openjarvis_rust = pytest.importorskip("openjarvis_rust")

    with pytest.raises(RuntimeError, match="Unknown engine|not found"):
        openjarvis_rust.SimpleAgent(engine_key="nonexistent_engine")


def test_omitted_host_uses_engine_specific_defaults():
    import inspect

    r = pytest.importorskip("openjarvis_rust")
    for name in [
        "SimpleAgent",
        "OrchestratorAgent",
        "NativeReActAgent",
        "NativeOpenHandsAgent",
        "MonitorOperativeAgent",
    ]:
        cls = getattr(r, name)
        assert inspect.signature(cls).parameters["host"].default is None
        assert cls(engine_key="vllm").agent_id()


@pytest.mark.parametrize(
    "engine_key,path", [("ollama", "/api/chat"), ("vllm", "/v1/chat/completions")]
)
def test_custom_host_receives_generation_request(tmp_path, engine_key, path):
    """Exercise the real extension against a local stub, never a provider API."""
    pytest.importorskip("openjarvis_rust")

    import os
    import subprocess
    import sys
    import time

    script = tmp_path / "server.py"
    port_file = tmp_path / "port"
    requests_file = tmp_path / "requests"
    script.write_text(
        """import json,sys
from http.server import BaseHTTPRequestHandler,HTTPServer
from pathlib import Path
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        record={'path':self.path,'model':body.get('model')}
        with open(sys.argv[2],'a',encoding='utf-8') as f:
            f.write(json.dumps(record)+'\\n')
        payload={'model':'host-probe','message':{'role':'assistant','content':'host-probe-ok'},'done':True,'prompt_eval_count':1,'eval_count':1,'choices':[{'message':{'role':'assistant','content':'host-probe-ok'},'finish_reason':'stop'}],'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}}
        data=json.dumps(payload).encode()
        self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
server=HTTPServer(('127.0.0.1',0),Handler)
Path(sys.argv[1]).write_text(str(server.server_port))
server.serve_forever()
""",
        encoding="utf-8",
    )
    env = {
        key: value
        for key, value in os.environ.items()
        if key.upper()
        in {
            "PATH",
            "SYSTEMROOT",
            "SYSTEMDRIVE",
            "COMSPEC",
            "PATHEXT",
            "TEMP",
            "TMP",
            "HOME",
            "USERPROFILE",
            "LOCALAPPDATA",
            "APPDATA",
            "LANG",
            "OPENJARVIS_HOME",
        }
    }
    env["NO_PROXY"] = "127.0.0.1,localhost"
    server = subprocess.Popen(
        [sys.executable, str(script), str(port_file), str(requests_file)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        env=env,
    )
    try:
        deadline = time.monotonic() + 10
        while (
            not port_file.exists()
            and server.poll() is None
            and time.monotonic() < deadline
        ):
            time.sleep(0.02)
        assert port_file.exists(), "Local stub failed to start"
        host = f"http://127.0.0.1:{port_file.read_text()}"
        code = (
            "import sys,openjarvis_rust as r; "
            "agent=r.SimpleAgent(engine_key=sys.argv[1],host=sys.argv[2],"
            "model='host-probe'); print(agent.run('probe').content)"
        )
        result = subprocess.run(
            [sys.executable, "-c", code, engine_key, host],
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert result.returncode == 0, result.stderr
        assert "host-probe-ok" in result.stdout
        import json

        requests = [json.loads(line) for line in requests_file.read_text().splitlines()]
        assert requests == [{"path": path, "model": "host-probe"}]
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)

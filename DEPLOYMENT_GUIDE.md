# NORA AI Deployment Guide

## Prerequisites

- Python 3.9+
- pip or poetry
- Git
- Optional: Docker
- Optional: Ollama (for local AI)

## Installation

### From PyPI (When Published)

```bash
pip install nora-ai
```

### From Source

```bash
git clone https://github.com/Demola3223/OpenJarvis.git
cd OpenJarvis
git checkout nora-ai-transformation
pip install -e .
```

### With Development Dependencies

```bash
pip install -e ".[dev]"
```

## Configuration

### Initial Setup

```bash
# Create config directory
mkdir -p ~/.openjarvis

# Copy default configs
cp nora-config-templates/branding.json ~/.openjarvis/
mkdir -p ~/.openjarvis/personalities
cp nora-config-templates/personalities/*.json ~/.openjarvis/personalities/
```

### config.toml

Create `~/.openjarvis/config.toml`:

```toml
# NORA Identity
[nora]
app_name = "NORA AI"
app_description = "Your Personal AI Assistant"
default_personality = "default"
router_mode = "auto"
enable_resource_monitoring = true
prefer_local_models = true
enable_voice_mode = true

# AI Settings
[intelligence]
preferred_engine = "ollama"
default_model = "qwen3.5:7b"
temperature = 0.7
max_tokens = 2048

# Device Settings
[devices]
local_port = 8765
enable_discovery = true

# Memory/Storage
[memory]
default_backend = "sqlite"
db_path = "~/.openjarvis/memory.db"
context_top_k = 5
context_max_tokens = 2048
```

## Running NORA

### Python SDK

```python
from openjarvis import Jarvis
from openjarvis.identity.modes import OperatingMode

# Initialize
nora = Jarvis()

# Set mode
nora.set_mode(OperatingMode.DEVELOPER)

# Ask a question
response = nora.ask("How do I implement OAuth in Python?")
print(response)

# Cleanup
nora.close()
```

### Command Line

```bash
# Interactive REPL
nora-cli

# Single query
nora-cli ask "What is the weather?"

# Set mode
nora-cli ask --mode developer "Debug this code"

# Stream response
nora-cli stream "Tell me a story"
```

### Web UI (Tauri)

```bash
cd frontend
npm install
npm run tauri dev
```

## Docker Deployment

### Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install NORA
COPY . .
RUN pip install -e .

# Create config directory
RUN mkdir -p ~/.openjarvis
COPY nora-config-templates/ ~/.openjarvis/

# Expose device server port
EXPOSE 8765

# Run device server
CMD ["python", "-c", "from openjarvis.network import DeviceServer; import asyncio; asyncio.run(DeviceServer('docker').start())"]
```

### docker-compose.yml

```yaml
version: '3.9'
services:
  nora:
    build: .
    ports:
      - "8765:8765"
    volumes:
      - ~/.openjarvis:/root/.openjarvis
    environment:
      - NORA_MODE=auto
      - NORA_ROUTER_MODE=auto
    restart: unless-stopped

  ollama:
    image: ollama/ollama:latest
    ports:
      - "11434:11434"
    volumes:
      - ollama:/root/.ollama
    restart: unless-stopped

volumes:
  ollama:
```

### Run with Docker

```bash
# Build image
docker build -t nora-ai .

# Run container
docker run -d \
  --name nora \
  -p 8765:8765 \
  -v ~/.openjarvis:/root/.openjarvis \
  nora-ai

# Or with docker-compose
docker-compose up -d
```

## Systemd Service (Linux)

### Create Service File

`/etc/systemd/system/nora.service`:

```ini
[Unit]
Description=NORA AI Device Server
After=network.target

[Service]
Type=simple
User=nora
WorkingDirectory=/home/nora
ExecStart=/usr/local/bin/nora-server
Restart=on-failure
RestartSec=10
Environment="NORA_CONFIG=/home/nora/.openjarvis/config.toml"

[Install]
WantedBy=multi-user.target
```

### Enable and Start

```bash
# Create nora user
sudo useradd -m -s /bin/bash nora

# Copy config
sudo mkdir -p /home/nora/.openjarvis
sudo cp nora-config-templates/* /home/nora/.openjarvis/
sudo chown -R nora:nora /home/nora/.openjarvis

# Enable service
sudo systemctl enable nora.service
sudo systemctl start nora.service

# Check status
sudo systemctl status nora.service
```

## Health Checks

### Test Installation

```python
from openjarvis import Jarvis
from openjarvis.identity.modes import OperatingMode

print("Testing NORA AI...")

# Test 1: Initialize
nora = Jarvis()
print(f"✓ Initialized: {nora.identity.branding.name}")

# Test 2: Mode switching
nora.set_mode(OperatingMode.DEVELOPER)
print(f"✓ Mode: {nora.identity.current_mode.value}")

# Test 3: Resource monitoring
resources = nora.resource_monitor.get_resources()
print(f"✓ Resources: {nora.resource_monitor.get_status_message()}")

# Test 4: Model listing
models = nora.list_models()
print(f"✓ Models available: {len(models)}")

# Test 5: Simple query
response = nora.ask("Say 'Hello, NORA AI is working!'")
print(f"✓ Response: {response}")

nora.close()
print("\n✓ All tests passed!")
```

### Health Check Endpoint

```python
import asyncio
from openjarvis.network import DeviceServer

async def health_check():
    server = DeviceServer("test-device")
    devices = server.get_connected_devices()
    return {
        "status": "healthy",
        "connected_devices": len(devices),
        "uptime": "..."
    }
```

## Troubleshooting

### Import Error: No module named 'openjarvis'

```bash
# Install in development mode
pip install -e .

# Or install from source
pip install git+https://github.com/Demola3223/OpenJarvis.git@nora-ai-transformation
```

### Ollama Not Found

```bash
# Install Ollama
curl https://ollama.ai/install.sh | sh

# Run Ollama
ollama serve

# Pull a model
ollama pull qwen3.5:7b
```

### Device Server Port Already in Use

```bash
# Change port in config.toml
[devices]
local_port = 8766  # Use different port

# Or kill existing process
lsof -i :8765
kill -9 <PID>
```

### Permission Denied

```bash
# Ensure config directory is readable
chmod 755 ~/.openjarvis
chmod 644 ~/.openjarvis/*.json

# For Docker, ensure volume is writable
docker run --user $(id -u):$(id -g) nora-ai
```

## Upgrading

```bash
# Check current version
nora-cli --version

# Upgrade from PyPI
pip install --upgrade nora-ai

# Upgrade from source
git pull origin main
pip install -e . --upgrade
```

## Uninstalling

```bash
# Remove pip package
pip uninstall nora-ai

# Remove config (optional)
rm -rf ~/.openjarvis

# Remove systemd service (if installed)
sudo systemctl disable nora.service
sudo rm /etc/systemd/system/nora.service
sudo systemctl daemon-reload
```

## Performance Tuning

### Model Selection

```toml
[intelligence]
# Fast local model (good for weak devices)
default_model = "qwen3.5:7b"  # 7GB

# Medium model (good balance)
default_model = "mistral-nemo"  # 12GB

# Powerful model (best quality)
default_model = "neural-chat"  # 13GB
```

### Resource Limits

```python
from openjarvis import Jarvis

nora = Jarvis()

# Auto-downgrade on low resources
if nora.resource_monitor.is_memory_critical():
    nora.model_router.set_mode(RouterMode.OFFLINE)
    # Now uses smaller local models
```

### Caching

```python
# Enable memory context caching
response = nora.ask(
    "Question",
    context=True  # Inject memory context
)

# Cache results
response = nora.ask_full(
    "Question",
    model="qwen3.5:7b"  # Avoid model selection overhead
)
```

## Monitoring

### Logs

```bash
# View logs
j tail -f ~/.openjarvis/nora.log

# Set log level
export LOGLEVEL=DEBUG
nora-cli

# Log to file
export LOGFILE=~/.openjarvis/nora.log
nora-server
```

### Metrics

```python
status = nora.get_status()
print(status["resources"])
print(status["router"])
print(status["identity"])
```

## Security Hardening

1. **Change default credentials** in `~/.openjarvis/devices.json`
2. **Use firewall** to restrict port 8765
3. **Enable TLS** for WebSocket (optional)
4. **Regular backups** of `~/.openjarvis/`
5. **Restrict permissions** on config files

## Support & Resources

- **Documentation:** https://github.com/Demola3223/OpenJarvis/wiki
- **Issues:** https://github.com/Demola3223/OpenJarvis/issues
- **Discussions:** https://github.com/Demola3223/OpenJarvis/discussions

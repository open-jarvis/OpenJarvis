# NORA AI Identity System

## Overview

NORA AI's identity system provides complete customization of:
- **Branding**: Name, logo, colors, UI text
- **Personality**: Communication style, behavior, capabilities
- **Operating Modes**: Role-based configurations (Developer, Research, Creator, etc.)
- **Model Routing**: Intelligent selection between local and cloud models

## Quick Start

### 1. Initialize NORA with Default Identity

```python
from openjarvis.identity.manager import IdentityManager

# Load default NORA identity
identity = IdentityManager(personality_name="default")

# Check current identity
print(identity.get_identity_summary())
```

### 2. Access Components

```python
# Access branding
print(identity.branding.name)  # "NORA AI"
print(identity.branding.colors.primary)  # "#6366f1"

# Access personality
print(identity.personality.communication.tone)  # "helpful"
print(identity.personality.capabilities.can_execute_code)  # True

# Check current mode
print(identity.current_mode)  # OperatingMode.GENERAL
```

### 3. Switch Operating Modes

```python
from openjarvis.identity.modes import OperatingMode

# Switch to developer mode
identity.set_mode(OperatingMode.DEVELOPER)

# Get mode-specific system prompt
system_prompt = identity.get_system_prompt(include_mode=True)
```

### 4. Use Model Router

```python
from openjarvis.identity.router import ModelRouter, RouterMode

router = ModelRouter(config)

# Set routing mode
router.set_mode(RouterMode.AUTO)  # or OFFLINE, ONLINE

# Select model for task
route = router.select_model(task_type="coding")
print(f"Using {route.model_id} on {route.provider}")
print(f"Reason: {route.reason}")
```

## Configuration Files

### Branding (`~/.openjarvis/branding.json`)

Controlls the app's appearance and messaging:

```json
{
  "name": "NORA AI",
  "colors": {
    "primary": "#6366f1",
    "secondary": "#ec4899"
  },
  "ui_text": {
    "app_name": "NORA AI",
    "welcome_message": "Hello! I'm NORA AI..."
  }
}
```

### Personality (`~/.openjarvis/personalities/default.json`)

Defines communication style and behavior:

```json
{
  "name": "NORA",
  "communication": {
    "tone": "helpful",
    "verbosity": "concise"
  },
  "capabilities": {
    "can_execute_code": true,
    "can_access_web": true
  }
}
```

## Available Personalities

Pre-configured personalities are available in `nora-config-templates/personalities/`:

- **default**: General-purpose assistant
- **developer**: Optimized for coding and debugging
- More coming: research, creative, analyst, blender

## Operating Modes

| Mode | Best For | Model Size | Features |
|------|----------|------------|----------|
| `GENERAL` | Normal tasks | Balanced | All tools enabled |
| `DEVELOPER` | Coding | Powerful | Terminal, Git, debugging |
| `RESEARCH` | Web research | Powerful | Web search, browser |
| `BUILDER` | Building projects | Powerful | File ops, full toolkit |
| `VOICE` | Voice interaction | Balanced | Concise responses |
| `CREATIVE` | Writing/design | Powerful | No code execution |
| `ANALYST` | Data analysis | Powerful | Code execution only |
| `BLENDER` | 3D modeling | Powerful | Blender Python API |
| `OFFLINE` | No internet | Lightweight | Local resources only |

## Model Router Modes

### AUTO (Default)
- Intelligently switches between local and cloud based on task complexity
- Falls back to local if offline
- Simple tasks → local models (fast, private)
- Complex tasks → cloud models (powerful, capable)

### OFFLINE
- Never use cloud APIs
- Always use local models
- Full privacy preservation

### ONLINE
- Prefer cloud models
- Fallback to local if cloud API fails
- Best for complex reasoning tasks

## Customization Examples

### Change Brand Identity

```python
identity.update_branding(
    name="My Personal AI",
    description="My custom AI assistant"
)
```

### Customize Personality

```python
identity.update_personality(
    name="Alex",
    communication={"tone": "casual", "use_emojis": True}
)
```

### Export Complete Configuration

```python
config = identity.export_config()
import json
with open("my_nora_config.json", "w") as f:
    json.dump(config, f, indent=2)
```

## Files Structure

```
~/.openjarvis/
├── branding.json                    # Brand configuration
├── config.toml                      # Main config
└── personalities/
    ├── default.json                 # Default personality
    ├── developer.json               # Developer personality
    └── [user custom personalities]
```

## Next Steps

1. **Integration with Jarvis SDK**: Update `Jarvis` class to use identity system for system prompts
2. **Frontend Updates**: Show brand colors, logo, and mode selector in UI
3. **Device Manager**: Extend identity to per-device configurations
4. **Android Client**: Use same identity configs for cross-device consistency

## API Reference

See docstrings in:
- `src/openjarvis/identity/manager.py` - IdentityManager
- `src/openjarvis/identity/personality.py` - PersonalityConfig
- `src/openjarvis/identity/branding.py` - BrandingConfig
- `src/openjarvis/identity/modes.py` - OperatingMode
- `src/openjarvis/identity/router.py` - ModelRouter

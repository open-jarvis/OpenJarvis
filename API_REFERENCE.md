# NORA AI API Reference

## Core Classes

### Jarvis (Main SDK)

```python
from openjarvis import Jarvis
from openjarvis.identity.modes import OperatingMode

jarvis = Jarvis(
    config=None,  # JarvisConfig or None for default
    config_path=None,  # Path to config.toml
    engine_key=None,  # Specific engine (ollama, openai, etc.)
    model=None,  # Specific model override
    personality_name="default"  # Personality to load
)

# Properties
jarvis.config  # JarvisConfig instance
jarvis.version  # OpenJarvis version
jarvis.identity  # IdentityManager
jarvis.model_router  # ModelRouter
jarvis.resource_monitor  # ResourceMonitor
jarvis.device_manager  # DeviceManager
jarvis.memory  # MemoryHandle

# Methods
jarvis.ask(query, model=None, agent=None, tools=None, ...)  # str
jarvis.ask_full(query, ...)  # Dict[str, Any]
await jarvis.ask_stream(query, ...)  # AsyncIterator[str]
await jarvis.ask_full_stream(query, ...)  # AsyncIterator[Dict]
jarvis.set_mode(mode: OperatingMode)  # None
jarvis.set_router_mode(mode: RouterMode)  # None
jarvis.get_system_prompt()  # str
jarvis.list_models()  # List[str]
jarvis.list_engines()  # List[str]
jarvis.get_status()  # Dict[str, Any]
jarvis.close()  # None
```

### IdentityManager

```python
from openjarvis.identity.manager import IdentityManager

identity = IdentityManager(
    config_dir=None,  # Path or ~/.openjarvis
    personality_name="default"
)

# Properties
identity.branding  # BrandingConfig
identity.personality  # PersonalityConfig
identity.current_mode  # OperatingMode

# Methods
identity.set_mode(mode: OperatingMode)  # None
identity.get_system_prompt(include_mode=True)  # str
identity.update_branding(**updates)  # None
identity.update_personality(**updates)  # None
identity.get_identity_summary()  # str
identity.export_config()  # Dict
```

### DeviceManager

```python
from openjarvis.devices import DeviceManager, DeviceType, DeviceOS

device_manager = DeviceManager(config_dir=None)

# Methods
device_manager.register_this_device(
    name="My PC",
    device_type=DeviceType.LAPTOP,
    os=DeviceOS.WINDOWS,
    ...
)  # DeviceInfo

device_manager.pair_device(
    name="My Phone",
    device_type=DeviceType.PHONE,
    os=DeviceOS.ANDROID,
    local_ip="192.168.1.100"
)  # DeviceInfo

device_manager.approve_device(device_id)  # bool
device_manager.remove_device(device_id)  # bool
device_manager.update_device_status(device_id, status)  # bool
device_manager.get_device(device_id)  # DeviceInfo | None
device_manager.get_devices_by_type(type)  # List[DeviceInfo]
device_manager.get_online_devices()  # List[DeviceInfo]
device_manager.send_command(target_id, action, payload)  # DeviceCommand
device_manager.get_status()  # Dict
```

### PermissionSystem

```python
from openjarvis.permissions import PermissionSystem, PermissionLevel

perm_system = PermissionSystem(approval_callback=None)

# Methods
perm_system.request_permission(permission_id, context=None)  # bool
perm_system.explain_action(permission_id)  # str
perm_system.grant_permission(permission_id)  # bool
perm_system.revoke_permission(permission_id)  # bool
perm_system.reset_permissions()  # None
perm_system.get_permission_level(permission_id)  # PermissionLevel | None

# Permission IDs (Examples)
"read_files"  # L1 - Safe
"edit_files"  # L2 - Confirmation
"delete_files"  # L3 - Explicit approval
"execute_code"  # L2 - Confirmation
"install_software"  # L2 - Confirmation
```

### ModelRouter

```python
from openjarvis.identity.router import ModelRouter, RouterMode

router = ModelRouter(config)

# Methods
router.set_mode(mode: RouterMode)  # None
router.set_connectivity(is_online: bool)  # None
router.select_model(task_type="general")  # ModelRoute
router.get_status()  # Dict

# Router Modes
RouterMode.AUTO  # Intelligent selection (default)
RouterMode.OFFLINE  # Local models only
RouterMode.ONLINE  # Cloud models preferred

# Task Types
"general"  # General queries
"coding"  # Code tasks
"research"  # Web research
"creative"  # Creative writing
"analysis"  # Data analysis
"blender"  # 3D modeling
```

## Tools

### BlenderController

```python
from openjarvis.tools.blender import BlenderController, BlenderScript

blender = BlenderController()

# Check availability
if blender.is_available():  # bool
    # Create script
    script = BlenderScript("my_scene")
    script.clear_scene()
    script.create_object("cube", "MainCube")
    script.set_object_location("MainCube", 0, 0, 5)
    script.render_to_file("/tmp/render.png")
    script.save(Path("/tmp/scene.py"))
    
    # Execute
    success = blender.run_script(Path("/tmp/scene.py"))  # bool
    
    # Open file
    blender.open_blend_file(Path("/tmp/model.blend"))  # bool
    
    # Get status
    status = blender.get_status()  # Dict
```

### SoftwareManager

```python
from openjarvis.tools.software_manager import SoftwareManager

software = SoftwareManager()

# Methods
software.register_app(
    name="Python",
    version="3.11.0",
    update_method="package_manager"
)  # InstalledApp

software.check_updates("Python")  # InstalledApp | None
software.get_update_instructions("Python")  # str | None
software.install_package("numpy", manager="pip")  # bool
software.get_installed_apps()  # List[InstalledApp]
software.get_apps_needing_updates()  # List[InstalledApp]
software.get_status()  # Dict
```

### FileSystemTool

```python
from openjarvis.tools.file_system import FileSystemTool

fs = FileSystemTool(permission_system=perm_system)

# Whitelist directories
fs.add_approved_directory(Path("/home/user/projects"))

# Methods
fs.read_file(Path("file.txt"))  # str | None
fs.write_file(Path("file.txt"), "content")  # bool
fs.delete_file(Path("file.txt"))  # bool
fs.list_directory(Path("./"))  # List[str] | None
fs.get_file_info(Path("file.txt"))  # Dict | None
fs.is_path_safe(Path("./"))  # bool
```

### TerminalTool

```python
from openjarvis.tools.terminal import TerminalTool

term = TerminalTool(permission_system=perm_system)

# Methods
result = term.execute(
    "ls -la",
    timeout=30,
    cwd=None
)  # Dict | None
# Returns: {"command", "return_code", "stdout", "stderr", "success"}

term.get_current_directory()  # str | None
term.list_directory("/home/user")  # List[str] | None
```

## Network

### DeviceServer

```python
from openjarvis.network import DeviceServer, MessageType

server = DeviceServer(
    device_id="pc-uuid",
    host="0.0.0.0",
    port=8765
)

# Methods
async def handle_command(message):
    print(f"Command: {message.payload}")

server.register_handler(MessageType.COMMAND_REQUEST, handle_command)

await server.start()  # None
await server.stop()  # None
await server.send_message(device_id, message)  # bool
await server.broadcast_message(message)  # int (count sent)
server.get_connected_devices()  # List[str]
```

### SecureTransport

```python
from openjarvis.network import SecureTransport, MessageType, DeviceMessage

transport = SecureTransport(
    device_id="my-device",
    shared_key="generated-during-pairing"
)

# Methods
message = transport.prepare_message(
    MessageType.COMMAND_REQUEST,
    target_device_id="other-device",
    payload={"action": "launch_app"}
)  # DeviceMessage (signed)

transport.verify_message(message)  # bool
```

### DevicePairingProtocol

```python
from openjarvis.network import DevicePairingProtocol

# Static methods
token = DevicePairingProtocol.generate_pairing_token()  # str (8 chars)
key = DevicePairingProtocol.generate_shared_key()  # str (64 chars)

request = DevicePairingProtocol.create_pairing_request(
    initiator_device_id="device1",
    initiator_name="My PC"
)  # Dict

response = DevicePairingProtocol.create_pairing_response(
    initiator_device_id="device1",
    responder_device_id="device2",
    responder_name="My Phone",
    pairing_token="ABCD1234"
)  # Dict
```

## Android

### AndroidController

```python
from openjarvis.android import AndroidController, AndroidCapability

android = AndroidController(device_id, secure_transport)

# Methods
await android.query_device_info()  # AndroidDeviceInfo | None
await android.query_installed_apps()  # List[AppInfo]
await android.launch_app("com.google.maps")  # bool
await android.open_url("https://github.com")  # bool
await android.send_notification(title, message)  # bool
await android.get_camera_permission()  # bool
await android.get_microphone_permission()  # bool
await android.read_clipboard()  # str | None
await android.write_clipboard(text)  # bool
await android.get_battery_status()  # Dict | None

# Capability checks
android.has_capability(AndroidCapability.CAMERA)  # bool
android.enable_capability(AndroidCapability.NOTIFICATIONS)
android.disable_capability(AndroidCapability.MICROPHONE)
```

## Configuration Classes

### BrandingConfig

```python
from openjarvis.identity.branding import BrandingConfig, ColorPalette

branding = BrandingConfig(
    name="NORA AI",
    description="Personal AI Assistant",
    colors=ColorPalette(
        primary="#6366f1",
        secondary="#ec4899"
    ),
    show_branding=True,
    enable_analytics=False
)
```

### PersonalityConfig

```python
from openjarvis.identity.personality import (
    PersonalityConfig,
    CommunicationStyle,
    Capabilities,
    Goals,
    Rules
)

personality = PersonalityConfig(
    name="NORA",
    role="Personal AI Assistant",
    communication=CommunicationStyle(
        tone="helpful",
        verbosity="concise"
    ),
    capabilities=Capabilities(
        can_execute_code=True,
        can_access_web=True
    )
)
```

## Examples

### Complete Workflow

```python
from openjarvis import Jarvis
from openjarvis.identity.modes import OperatingMode

# Initialize
nora = Jarvis(personality_name="developer")
print(nora.identity.get_identity_summary())

# Switch mode
nora.set_mode(OperatingMode.DEVELOPER)

# Ask question
response = nora.ask(
    "How do I use async/await in Python?",
    task_type="coding"
)
print(response)

# Stream response
import asyncio

async def stream_example():
    async for token in nora.ask_stream("Tell me a joke"):
        print(token, end="", flush=True)

asyncio.run(stream_example())

# Cleanup
nora.close()
```

### Using Tools

```python
from openjarvis import Jarvis
from openjarvis.tools.blender import BlenderController
from openjarvis.tools.file_system import FileSystemTool

nora = Jarvis()

# Use Blender
blender = BlenderController()
if blender.is_available():
    # ... create scene ...
    blender.run_script(Path("scene.py"))

# Use File System
fs = FileSystemTool(nora.permission_system)
fs.add_approved_directory(Path("/home/user/projects"))
content = fs.read_file(Path("/home/user/projects/main.py"))

nora.close()
```

### Device Management

```python
from openjarvis import Jarvis
from openjarvis.devices import DeviceType, DeviceOS

nora = Jarvis()

# Register this device
pc = nora.device_manager.register_this_device(
    "My PC",
    DeviceType.PC,
    DeviceOS.WINDOWS
)

# Pair with phone
phone = nora.device_manager.pair_device(
    "My Phone",
    DeviceType.PHONE,
    DeviceOS.ANDROID
)

# Approve phone
nora.device_manager.approve_device(phone.device_id)

# Get status
print(nora.device_manager.get_status())

nora.close()
```

## Error Handling

```python
from openjarvis import Jarvis

try:
    nora = Jarvis()
    response = nora.ask("Query")
except FileNotFoundError:
    print("Config file not found")
except RuntimeError as e:
    print(f"No inference engine: {e}")
except Exception as e:
    print(f"Error: {e}")
finally:
    nora.close()
```

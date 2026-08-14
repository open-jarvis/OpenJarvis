"""Frontend UI components for NORA AI — Device Panel, Mode Selector, etc."""

# This file documents the React component updates needed for the frontend

"""
NORA AI FRONTEND COMPONENTS

Updates to frontend/src/ for NORA AI identity and device system:

NEW COMPONENTS:

1. DevicePanel.tsx
   - Display connected devices
   - Show device status (online/offline)
   - Display device capabilities
   - Enable/disable capabilities
   - Remove/disconnect devices
   - Device information popup

2. ModeSelector.tsx
   - Switch between operating modes
   - Show mode description
   - Display recommended model size
   - Show mode-specific tools
   - Persist selected mode

3. IdentityCard.tsx
   - Display NORA branding
   - Show current personality
   - Display app name and colors
   - Quick settings access

4. ConnectivityIndicator.tsx
   - Show online/offline status
   - Display router mode (AUTO/OFFLINE/ONLINE)
   - Show network quality
   - Battery/resource indicator

5. PermissionDialog.tsx
   - Display permission request
   - Show action description
   - Accept/Deny buttons
   - Permission level indicator (L1/L2/L3)

6. StatusPanel.tsx
   - Show AI thinking/processing
   - Display active tools
   - Show memory context being used
   - Resource usage (CPU/RAM/GPU)

7. CommandInput.tsx
   - Text input for commands
   - Voice input toggle
   - File attachment support
   - Mode-aware suggestions

COMPONENT HIERARCHY:

App.tsx
├─ Header
│  ├─ BrandingHeader
│  ├─ ConnectivityIndicator
│  └─ ModeSelector
├─ MainContent
│  ├─ ChatInterface
│  │  ├─ CommandInput
│  │  ├─ MessageList
│  │  └─ StatusPanel
│  └─ DevicePanel
│     ├─ DeviceCard (repeating)
│     └─ AddDeviceButton
├─ PermissionDialog (modal)
├─ SettingsPanel
│  ├─ PersonalitySettings
│  ├─ BrandingSettings
│  ├─ DeviceSettings
│  └─ PermissionSettings
└─ Footer
   ├─ ResourceMonitor
   └─ StatusIndicator

STYLING:

- Use BrandingConfig colors for theming
- Responsive design (mobile-first)
- Dark mode by default
- NORA brand colors:
  - Primary: #6366f1 (Indigo)
  - Secondary: #ec4899 (Pink)
  - Accent: #f59e0b (Amber)

STATE MANAGEMENT:

- Zustand store for:
  - Current mode
  - Connected devices
  - Connectivity status
  - Branding config
  - Permission requests
  - Chat history

API INTEGRATION:

- WebSocket connection to DeviceServer
- REST API to /api/identity/ endpoints
- Real-time updates for device status
- Command/response streaming

ACCESSIBILITY:

- ARIA labels for all components
- Keyboard navigation support
- Color contrast compliance
- Screen reader support
- Reduced motion support
"""

print("Frontend components documentation ready.")

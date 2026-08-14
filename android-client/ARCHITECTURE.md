"""Android Client Architecture for NORA AI — Kotlin/Compose companion app."""

# This is the architecture blueprint for the Android client
# Implementation follows standard Android patterns

"""
NORA ANDROID CLIENT ARCHITECTURE

Project Structure:

app/
├── src/main/kotlin/com/nora/ai/
│   ├── MainActivity.kt                 # Main UI entry point
│   ├── App.kt                          # Application class
│   ├── di/                             # Dependency injection
│   │   └── AppModule.kt
│   ├── data/
│   │   ├── local/
│   │   │   ├── DeviceDatabase.kt      # Local device registry
│   │   │   ├── PreferencesStore.kt    # Encrypted preferences
│   │   │   └── CredentialStore.kt     # Secure credential storage
│   │   ├── remote/
│   │   │   ├── NoraApiService.kt      # REST API client
│   │   │   └── DeviceService.kt       # Device communication
│   │   └── repository/
│   │       ├── DeviceRepository.kt
│   │       └── CommandRepository.kt
│   ├── domain/
│   │   ├── model/
│   │   │   ├── Device.kt
│   │   │   ├── Command.kt
│   │   │   └── FileTransfer.kt
│   │   └── usecase/
│   │       ├── PairDeviceUseCase.kt
│   │       ├── SendCommandUseCase.kt
│   │       └── TransferFileUseCase.kt
│   ├── presentation/
│   │   ├── MainActivity.kt
│   │   ├── ui/
│   │   │   ├── screens/
│   │   │   │   ├── DeviceListScreen.kt
│   │   │   │   ├── PairingScreen.kt
│   │   │   │   ├── ChatScreen.kt
│   │   │   │   └── SettingsScreen.kt
│   │   │   ├── components/
│   │   │   │   ├── DeviceCard.kt
│   │   │   │   ├── CommandInput.kt
│   │   │   │   └── StatusIndicator.kt
│   │   │   └── theme/
│   │   │       ├── Color.kt
│   │   │       ├── Typography.kt
│   │   │       └── Theme.kt
│   │   └── viewmodel/
│   │       ├── DeviceViewModel.kt
│   │       ├── ChatViewModel.kt
│   │       ├── PairingViewModel.kt
│   │       └── SettingsViewModel.kt
│   ├── service/
│   │   ├── DeviceConnectionService.kt  # Background connection
│   │   ├── CommandExecutorService.kt   # Execute remote commands
│   │   └── FileTransferService.kt      # Background transfers
│   └── util/
│       ├── NetworkUtil.kt
│       ├── SecurityUtil.kt
│       ├── LogUtil.kt
│       └── NotificationUtil.kt
├── src/main/AndroidManifest.xml
├── build.gradle
└── proguard-rules.pro

Dependencies:
- Jetpack Compose (UI)
- Hilt (DI)
- Room (Database)
- Retrofit + OkHttp (Networking)
- Kotlin Coroutines (Async)
- DataStore (Encrypted preferences)
- WorkManager (Background jobs)
"""

# Architecture Layers
"""
┌─────────────────────────────────────────┐
│      ANDROID UI (Jetpack Compose)       │
│  ├─ Device List Screen                  │
│  ├─ Chat/Command Screen                 │
│  ├─ Pairing Workflow                    │
│  └─ Settings Panel                      │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│   PRESENTATION LAYER (ViewModels)       │
│  ├─ DeviceViewModel                     │
│  ├─ ChatViewModel                       │
│  ├─ PairingViewModel                    │
│  └─ SettingsViewModel                   │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│   DOMAIN LAYER (Use Cases & Models)     │
│  ├─ Device pairing logic                │
│  ├─ Command sending                     │
│  ├─ File transfer                       │
│  └─ Authentication                      │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│   DATA LAYER (Repository Pattern)       │
│  ├─ Local: Room database, DataStore     │
│  ├─ Remote: REST API over HTTPS         │
│  └─ Sync: Local-first with cloud backup │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│   SERVICES (Background Work)            │
│  ├─ DeviceConnectionService             │
│  ├─ CommandExecutorService              │
│  └─ FileTransferService                 │
└─────────────────────────────────────────┘
"""

print("Android Client architecture blueprint ready.")

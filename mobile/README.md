# OpenJarvis Mobile App

A Flutter-based mobile AI assistant that communicates with the OpenJarvis backend via WebSocket. Built with voice input/output capabilities for a seamless hands-free experience.

## Features

✨ **Voice Control**
- Real-time speech-to-text input
- Natural text-to-speech responses
- Wake word detection (customizable)

📱 **Cross-Platform**
- iOS and Android support
- Responsive Material 3 design
- Dark mode support

🔌 **Backend Integration**
- WebSocket communication with OpenJarvis backend
- Real-time streaming responses
- Error handling and reconnection

⚙️ **Customizable Settings**
- Backend URL configuration
- API key management
- Voice parameters (rate, volume)
- Language selection
- Notifications

## Getting Started

### Prerequisites
- Flutter 3.0+
- Dart 3.0+
- iOS: Xcode 14+
- Android: Android Studio with SDK 21+

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/open-jarvis/OpenJarvis.git
   cd OpenJarvis/mobile
   ```

2. **Install dependencies**
   ```bash
   flutter pub get
   ```

3. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

4. **Run the app**
   ```bash
   # iOS
   flutter run -d iphone
   
   # Android
   flutter run -d android
   
   # Web (experimental)
   flutter run -d chrome
   ```

## Project Structure

```
mobile/
├── lib/
│   ├── main.dart                 # App entry point
│   ├── screens/
│   │   ├── home_screen.dart      # Main navigation
│   │   ├── chat_screen.dart      # Chat interface
│   │   └── settings_screen.dart  # Settings
│   ├── providers/
│   │   ├── jarvis_provider.dart  # Main state management
│   │   └── settings_provider.dart # Settings state
│   └── services/
│       ├── websocket_service.dart # Backend communication
│       └── voice_service.dart     # Voice input/output
├── pubspec.yaml                  # Dependencies
└── README.md                      # This file
```

## Configuration

### Backend URL
Update the `BACKEND_URL` in `.env`:
```
BACKEND_URL=ws://your-server:8000/ws
```

### API Key
Set your API key in `.env`:
```
API_KEY=your-secret-key
```

### Voice Settings
In the app's Settings screen, you can:
- Change the wake word (default: "jarvis")
- Adjust speech rate (0.5 - 2.0x)
- Control TTS volume (0.0 - 1.0)
- Select language
- Enable/disable voice input

## Architecture

### State Management (Provider)
- **JarvisProvider**: Manages conversation state, voice input/output, and WebSocket communication
- **SettingsProvider**: Persists user settings using SharedPreferences

### Services
- **WebSocketService**: Handles real-time communication with backend
- **VoiceService**: Manages speech-to-text and text-to-speech

### UI Screens
- **HomeScreen**: Tab navigation between Chat and Settings
- **ChatScreen**: Message display and input interface
- **SettingsScreen**: Configurable app settings

## Communication Protocol

### WebSocket Messages

**Client → Server (Text Message)**
```json
{
  "type": "query",
  "text": "What's the weather?",
  "timestamp": "2024-08-16T10:30:00Z"
}
```

**Server → Client (Response)**
```json
{
  "type": "response",
  "text": "The weather is sunny today...",
  "timestamp": "2024-08-16T10:30:05Z"
}
```

**Server → Client (Thinking)**
```json
{
  "type": "thinking",
  "text": "Let me search for that information..."
}
```

**Server → Client (Error)**
```json
{
  "type": "error",
  "message": "Failed to process request"
}
```

## Building for Production

### iOS
```bash
flutter build ios --release
```

### Android
```bash
flutter build apk --release
flutter build appbundle --release  # For Google Play
```

## Dependencies

- **provider**: State management
- **web_socket_channel**: WebSocket client
- **speech_to_text**: Speech recognition
- **flutter_tts**: Text-to-speech
- **record**: Audio recording
- **shared_preferences**: Local storage
- **logger**: Logging
- **flutter_dotenv**: Environment configuration

## Troubleshooting

### Microphone Permission Denied
- iOS: Add to `ios/Runner/Info.plist`:
  ```xml
  <key>NSMicrophoneUsageDescription</key>
  <string>This app needs microphone access for voice commands</string>
  ```
- Android: Add to `android/app/src/main/AndroidManifest.xml`:
  ```xml
  <uses-permission android:name="android.permission.RECORD_AUDIO" />
  <uses-permission android:name="android.permission.INTERNET" />
  ```

### WebSocket Connection Failed
- Verify backend URL is correct
- Check API key is set
- Ensure backend server is running

### Speech Recognition Not Working
- Check microphone permissions
- Verify internet connection (some STT engines require it)
- Try different language settings

## Contributing

Contributions are welcome! Please:
1. Create a feature branch
2. Make your changes
3. Submit a pull request

See [CONTRIBUTING.md](../CONTRIBUTING.md) for details.

## License

Apache License 2.0 - See [LICENSE](../LICENSE)

## Support

- **Discord**: [discord.gg/CMVBmDQ5Fj](https://discord.gg/CMVBmDQ5Fj)
- **GitHub Issues**: [github.com/open-jarvis/OpenJarvis/issues](https://github.com/open-jarvis/OpenJarvis/issues)
- **Documentation**: [open-jarvis.github.io/OpenJarvis](https://open-jarvis.github.io/OpenJarvis/)

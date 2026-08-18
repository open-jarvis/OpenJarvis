import 'package:flutter/foundation.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import '../services/websocket_service.dart';
import '../services/voice_service.dart';
import 'package:logger/logger.dart';

class Message {
  final String id;
  final String text;
  final bool isUser;
  final DateTime timestamp;
  final String? voiceUrl;

  Message({
    required this.id,
    required this.text,
    required this.isUser,
    required this.timestamp,
    this.voiceUrl,
  });
}

class JarvisProvider extends ChangeNotifier {
  late WebSocketService _webSocketService;
  late VoiceService _voiceService;
  final Logger _logger = Logger();

  List<Message> _messages = [];
  bool _isLoading = false;
  bool _isListening = false;
  String? _error;

  List<Message> get messages => _messages;
  bool get isLoading => _isLoading;
  bool get isListening => _isListening;
  String? get error => _error;

  JarvisProvider() {
    _initialize();
  }

  Future<void> _initialize() async {
    try {
      final serverUrl = dotenv.env['BACKEND_URL'] ?? 'ws://localhost:8000/ws';
      final apiKey = dotenv.env['API_KEY'] ?? '';

      _webSocketService = WebSocketService(
        serverUrl: serverUrl,
        apiKey: apiKey,
      );

      _voiceService = VoiceService();

      // Initialize voice service
      await _voiceService.initialize();

      // Connect to backend
      await _webSocketService.connect();

      // Listen to WebSocket messages
      _webSocketService.messages.listen((message) {
        _handleWebSocketMessage(message);
      });

      // Listen to voice input
      _voiceService.transcriptionStream.listen((text) {
        _handleTranscription(text);
      });

      _voiceService.listeningStream.listen((listening) {
        _isListening = listening;
        notifyListeners();
      });

      _logger.i('JarvisProvider initialized');
    } catch (e) {
      _error = 'Initialization error: $e';
      _logger.e(_error);
      notifyListeners();
    }
  }

  /// Send a text message
  Future<void> sendMessage(String text) async {
    try {
      // Add user message to list
      final userMessage = Message(
        id: DateTime.now().millisecondsSinceEpoch.toString(),
        text: text,
        isUser: true,
        timestamp: DateTime.now(),
      );

      _messages.add(userMessage);
      _isLoading = true;
      _error = null;
      notifyListeners();

      // Send to backend
      await _webSocketService.sendQuery(text);
    } catch (e) {
      _error = 'Error sending message: $e';
      _logger.e(_error);
      _isLoading = false;
      notifyListeners();
    }
  }

  /// Start voice input
  Future<void> startVoiceInput() async {
    try {
      _error = null;
      await _voiceService.startListening();
      notifyListeners();
    } catch (e) {
      _error = 'Error starting voice: $e';
      _logger.e(_error);
      notifyListeners();
    }
  }

  /// Stop voice input
  Future<void> stopVoiceInput() async {
    try {
      await _voiceService.stopListening();
      notifyListeners();
    } catch (e) {
      _error = 'Error stopping voice: $e';
      _logger.e(_error);
      notifyListeners();
    }
  }

  /// Handle WebSocket message from backend
  void _handleWebSocketMessage(Map<String, dynamic> message) {
    try {
      final type = message['type'] as String?;

      switch (type) {
        case 'response':
          final responseText = message['text'] as String? ?? '';
          final botMessage = Message(
            id: DateTime.now().millisecondsSinceEpoch.toString(),
            text: responseText,
            isUser: false,
            timestamp: DateTime.now(),
          );

          _messages.add(botMessage);
          _isLoading = false;

          // Speak the response
          _voiceService.speak(responseText);
          break;

        case 'error':
          _error = message['message'] as String? ?? 'Unknown error';
          _isLoading = false;
          break;

        case 'thinking':
          // Show thinking state
          _logger.d('Jarvis thinking: ${message["text"]}');
          break;
      }

      notifyListeners();
    } catch (e) {
      _error = 'Error handling message: $e';
      _logger.e(_error);
      notifyListeners();
    }
  }

  /// Handle voice transcription
  void _handleTranscription(String text) {
    // Add partial transcription to last user message or create new one
    if (_messages.isEmpty || !_messages.last.isUser) {
      final tempMessage = Message(
        id: 'temp_${DateTime.now().millisecondsSinceEpoch}',
        text: text,
        isUser: true,
        timestamp: DateTime.now(),
      );
      _messages.add(tempMessage);
    } else {
      // Update existing user message
      _messages[_messages.length - 1] = Message(
        id: _messages.last.id,
        text: text,
        isUser: true,
        timestamp: _messages.last.timestamp,
      );
    }

    notifyListeners();
  }

  /// Clear conversation
  void clearMessages() {
    _messages.clear();
    _error = null;
    notifyListeners();
  }

  @override
  void dispose() {
    _voiceService.dispose();
    _webSocketService.dispose();
    super.dispose();
  }
}
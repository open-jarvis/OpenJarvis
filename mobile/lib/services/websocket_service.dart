import 'dart:async';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:logger/logger.dart';
import 'dart:convert';

class WebSocketService {
  final String serverUrl;
  final String apiKey;
  final Logger _logger = Logger();
  
  WebSocketChannel? _channel;
  final StreamController<Map<String, dynamic>> _messageStream = 
      StreamController<Map<String, dynamic>>.broadcast();
  
  bool _isConnected = false;

  WebSocketService({
    required this.serverUrl,
    required this.apiKey,
  });

  Stream<Map<String, dynamic>> get messages => _messageStream.stream;
  bool get isConnected => _isConnected;

  /// Connect to WebSocket server
  Future<bool> connect() async {
    try {
      final uri = Uri.parse(serverUrl);
      _channel = WebSocketChannel.connect(uri);
      
      // Send authentication
      _channel!.sink.add(jsonEncode({
        'type': 'auth',
        'api_key': apiKey,
      }));

      // Listen for messages
      _channel!.stream.listen(
        (message) => _handleMessage(message),
        onError: (error) => _handleError(error),
        onDone: () => _handleDisconnect(),
      );

      _isConnected = true;
      _logger.i('WebSocket connected: $serverUrl');
      return true;
    } catch (e) {
      _logger.e('WebSocket connection failed: $e');
      _isConnected = false;
      return false;
    }
  }

  /// Send voice audio to backend
  Future<void> sendVoiceData(List<int> audioBytes) async {
    if (!_isConnected) {
      _logger.w('WebSocket not connected');
      return;
    }

    try {
      _channel!.sink.add(jsonEncode({
        'type': 'voice',
        'data': base64Encode(audioBytes),
        'timestamp': DateTime.now().toIso8601String(),
      }));
    } catch (e) {
      _logger.e('Error sending voice data: $e');
    }
  }

  /// Send text query to backend
  Future<void> sendQuery(String query) async {
    if (!_isConnected) {
      _logger.w('WebSocket not connected');
      return;
    }

    try {
      _channel!.sink.add(jsonEncode({
        'type': 'query',
        'text': query,
        'timestamp': DateTime.now().toIso8601String(),
      }));
    } catch (e) {
      _logger.e('Error sending query: $e');
    }
  }

  /// Handle incoming messages
  void _handleMessage(dynamic message) {
    try {
      final data = jsonDecode(message);
      _messageStream.add(data);
      _logger.d('Received message: ${data["type"]}');
    } catch (e) {
      _logger.e('Error parsing message: $e');
    }
  }

  /// Handle connection errors
  void _handleError(dynamic error) {
    _logger.e('WebSocket error: $error');
    _isConnected = false;
  }

  /// Handle disconnection
  void _handleDisconnect() {
    _logger.i('WebSocket disconnected');
    _isConnected = false;
  }

  /// Disconnect from server
  Future<void> disconnect() async {
    await _channel?.sink.close();
    _isConnected = false;
    _logger.i('WebSocket closed');
  }

  void dispose() {
    _messageStream.close();
    disconnect();
  }
}
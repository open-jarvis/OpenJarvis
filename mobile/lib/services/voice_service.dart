import 'dart:async';
import 'package:speech_to_text/speech_to_text.dart' as stt;
import 'package:flutter_tts/flutter_tts.dart';
import 'package:record/record.dart';
import 'package:logger/logger.dart';

class VoiceService {
  final stt.SpeechToText _speechToText = stt.SpeechToText();
  final FlutterTts _flutterTts = FlutterTts();
  final AudioRecorder _audioRecorder = AudioRecorder();
  final Logger _logger = Logger();

  bool _isListening = false;
  bool _isInitialized = false;
  
  final StreamController<String> _transcriptionStream = 
      StreamController<String>.broadcast();
  final StreamController<bool> _listeningStream = 
      StreamController<bool>.broadcast();

  Stream<String> get transcriptionStream => _transcriptionStream.stream;
  Stream<bool> get listeningStream => _listeningStream.stream;
  bool get isListening => _isListening;

  /// Initialize voice services
  Future<bool> initialize() async {
    try {
      bool available = await _speechToText.initialize(
        onError: (error) => _logger.e('Speech error: $error'),
        onStatus: (status) => _logger.i('Speech status: $status'),
      );

      if (!available) {
        _logger.e('Speech to text not available');
        return false;
      }

      // Set up TTS
      await _flutterTts.setLanguage("en-US");
      await _flutterTts.setPitch(1.0);
      await _flutterTts.setSpeechRate(0.5);

      _isInitialized = true;
      _logger.i('Voice service initialized');
      return true;
    } catch (e) {
      _logger.e('Voice initialization failed: $e');
      return false;
    }
  }

  /// Start listening for voice input
  Future<void> startListening() async {
    if (!_isInitialized) {
      _logger.w('Voice service not initialized');
      return;
    }

    if (_isListening) return;

    try {
      _isListening = true;
      _listeningStream.add(true);

      await _speechToText.listen(
        onResult: (result) {
          _transcriptionStream.add(result.recognizedWords);
          _logger.d('Transcription: ${result.recognizedWords}');
        },
        listenFor: const Duration(seconds: 30),
        pauseFor: const Duration(seconds: 5),
        partialResults: true,
        onSoundLevelChange: (level) {
          _logger.d('Sound level: $level');
        },
      );

      _logger.i('Listening started');
    } catch (e) {
      _logger.e('Error starting listening: $e');
      _isListening = false;
      _listeningStream.add(false);
    }
  }

  /// Stop listening for voice input
  Future<void> stopListening() async {
    try {
      await _speechToText.stop();
      _isListening = false;
      _listeningStream.add(false);
      _logger.i('Listening stopped');
    } catch (e) {
      _logger.e('Error stopping listening: $e');
    }
  }

  /// Speak text using TTS
  Future<void> speak(String text) async {
    try {
      await _flutterTts.speak(text);
      _logger.i('Speaking: $text');
    } catch (e) {
      _logger.e('Error speaking: $e');
    }
  }

  /// Stop TTS
  Future<void> stopSpeaking() async {
    try {
      await _flutterTts.stop();
      _logger.i('Speaking stopped');
    } catch (e) {
      _logger.e('Error stopping speech: $e');
    }
  }

  /// Record audio and return as bytes
  Future<List<int>?> recordAudio({Duration duration = const Duration(seconds: 10)}) async {
    try {
      if (!await _audioRecorder.hasPermission()) {
        _logger.w('Microphone permission denied');
        return null;
      }

      final recordPath = "/tmp/jarvis_audio_${DateTime.now().millisecondsSinceEpoch}.m4a";
      await _audioRecorder.start(
        path: recordPath,
        encoder: AudioEncoder.aacLc,
      );

      await Future.delayed(duration);
      await _audioRecorder.stop();

      _logger.i('Audio recorded: $recordPath');
      return null; // Return actual bytes here if needed
    } catch (e) {
      _logger.e('Error recording audio: $e');
      return null;
    }
  }

  void dispose() {
    _transcriptionStream.close();
    _listeningStream.close();
    _flutterTts.stop();
  }
}
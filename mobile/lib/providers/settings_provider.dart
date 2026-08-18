import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:logger/logger.dart';

class SettingsProvider extends ChangeNotifier {
  final Logger _logger = Logger();
  late SharedPreferences _prefs;

  String _wakeWord = 'jarvis';
  bool _voiceEnabled = true;
  bool _notificationsEnabled = true;
  double _speechRate = 0.5;
  double _ttsVolume = 1.0;
  String _language = 'en-US';
  String _backendUrl = 'ws://localhost:8000/ws';
  String _apiKey = '';
  bool _darkMode = false;

  // Getters
  String get wakeWord => _wakeWord;
  bool get voiceEnabled => _voiceEnabled;
  bool get notificationsEnabled => _notificationsEnabled;
  double get speechRate => _speechRate;
  double get ttsVolume => _ttsVolume;
  String get language => _language;
  String get backendUrl => _backendUrl;
  String get apiKey => _apiKey;
  bool get darkMode => _darkMode;

  SettingsProvider() {
    _initialize();
  }

  Future<void> _initialize() async {
    try {
      _prefs = await SharedPreferences.getInstance();
      await _loadSettings();
      _logger.i('Settings initialized');
    } catch (e) {
      _logger.e('Error initializing settings: $e');
    }
  }

  Future<void> _loadSettings() async {
    _wakeWord = _prefs.getString('wakeWord') ?? 'jarvis';
    _voiceEnabled = _prefs.getBool('voiceEnabled') ?? true;
    _notificationsEnabled = _prefs.getBool('notificationsEnabled') ?? true;
    _speechRate = _prefs.getDouble('speechRate') ?? 0.5;
    _ttsVolume = _prefs.getDouble('ttsVolume') ?? 1.0;
    _language = _prefs.getString('language') ?? 'en-US';
    _backendUrl = _prefs.getString('backendUrl') ?? 'ws://localhost:8000/ws';
    _apiKey = _prefs.getString('apiKey') ?? '';
    _darkMode = _prefs.getBool('darkMode') ?? false;
  }

  Future<void> setWakeWord(String word) async {
    _wakeWord = word;
    await _prefs.setString('wakeWord', word);
    notifyListeners();
    _logger.i('Wake word set to: $word');
  }

  Future<void> setVoiceEnabled(bool enabled) async {
    _voiceEnabled = enabled;
    await _prefs.setBool('voiceEnabled', enabled);
    notifyListeners();
  }

  Future<void> setNotificationsEnabled(bool enabled) async {
    _notificationsEnabled = enabled;
    await _prefs.setBool('notificationsEnabled', enabled);
    notifyListeners();
  }

  Future<void> setSpeechRate(double rate) async {
    _speechRate = rate;
    await _prefs.setDouble('speechRate', rate);
    notifyListeners();
  }

  Future<void> setTtsVolume(double volume) async {
    _ttsVolume = volume;
    await _prefs.setDouble('ttsVolume', volume);
    notifyListeners();
  }

  Future<void> setLanguage(String lang) async {
    _language = lang;
    await _prefs.setString('language', lang);
    notifyListeners();
  }

  Future<void> setBackendUrl(String url) async {
    _backendUrl = url;
    await _prefs.setString('backendUrl', url);
    notifyListeners();
    _logger.i('Backend URL set to: $url');
  }

  Future<void> setApiKey(String key) async {
    _apiKey = key;
    await _prefs.setString('apiKey', key);
    notifyListeners();
    _logger.i('API key configured');
  }

  Future<void> setDarkMode(bool dark) async {
    _darkMode = dark;
    await _prefs.setBool('darkMode', dark);
    notifyListeners();
  }

  Future<void> resetSettings() async {
    await _prefs.clear();
    _wakeWord = 'jarvis';
    _voiceEnabled = true;
    _notificationsEnabled = true;
    _speechRate = 0.5;
    _ttsVolume = 1.0;
    _language = 'en-US';
    _backendUrl = 'ws://localhost:8000/ws';
    _apiKey = '';
    _darkMode = false;
    notifyListeners();
    _logger.i('Settings reset to defaults');
  }
}
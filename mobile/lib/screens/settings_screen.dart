import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/settings_provider.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({Key? key}) : super(key: key);

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  late TextEditingController _backendUrlController;
  late TextEditingController _apiKeyController;
  late TextEditingController _wakeWordController;

  @override
  void initState() {
    super.initState();
    final settingsProvider = Provider.of<SettingsProvider>(context, listen: false);
    _backendUrlController = TextEditingController(text: settingsProvider.backendUrl);
    _apiKeyController = TextEditingController(text: settingsProvider.apiKey);
    _wakeWordController = TextEditingController(text: settingsProvider.wakeWord);
  }

  @override
  void dispose() {
    _backendUrlController.dispose();
    _apiKeyController.dispose();
    _wakeWordController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<SettingsProvider>(
      builder: (context, settingsProvider, _) {
        return Scaffold(
          appBar: AppBar(
            title: const Text('Settings'),
            centerTitle: true,
          ),
          body: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              // Server Configuration
              _SettingSection(
                title: 'Server Configuration',
                children: [
                  _SettingTextField(
                    label: 'Backend URL',
                    controller: _backendUrlController,
                    onChanged: settingsProvider.setBackendUrl,
                    hint: 'ws://localhost:8000/ws',
                  ),
                  const SizedBox(height: 16),
                  _SettingTextField(
                    label: 'API Key',
                    controller: _apiKeyController,
                    onChanged: settingsProvider.setApiKey,
                    hint: 'Enter your API key',
                    obscureText: true,
                  ),
                ],
              ),
              const SizedBox(height: 24),
              // Voice Settings
              _SettingSection(
                title: 'Voice Settings',
                children: [
                  _SettingTextField(
                    label: 'Wake Word',
                    controller: _wakeWordController,
                    onChanged: settingsProvider.setWakeWord,
                    hint: 'jarvis',
                  ),
                  const SizedBox(height: 16),
                  _SettingSwitch(
                    label: 'Voice Input Enabled',
                    value: settingsProvider.voiceEnabled,
                    onChanged: settingsProvider.setVoiceEnabled,
                  ),
                  const SizedBox(height: 16),
                  _SettingSlider(
                    label: 'Speech Rate',
                    value: settingsProvider.speechRate,
                    onChanged: settingsProvider.setSpeechRate,
                    min: 0.5,
                    max: 2.0,
                  ),
                  const SizedBox(height: 16),
                  _SettingSlider(
                    label: 'TTS Volume',
                    value: settingsProvider.ttsVolume,
                    onChanged: settingsProvider.setTtsVolume,
                    min: 0.0,
                    max: 1.0,
                  ),
                ],
              ),
              const SizedBox(height: 24),
              // General Settings
              _SettingSection(
                title: 'General',
                children: [
                  _SettingSwitch(
                    label: 'Notifications Enabled',
                    value: settingsProvider.notificationsEnabled,
                    onChanged: settingsProvider.setNotificationsEnabled,
                  ),
                  const SizedBox(height: 16),
                  _SettingSwitch(
                    label: 'Dark Mode',
                    value: settingsProvider.darkMode,
                    onChanged: settingsProvider.setDarkMode,
                  ),
                ],
              ),
              const SizedBox(height: 24),
              // Reset Button
              ElevatedButton.icon(
                onPressed: () {
                  showDialog(
                    context: context,
                    builder: (context) => AlertDialog(
                      title: const Text('Reset Settings'),
                      content: const Text('Are you sure you want to reset all settings to default?'),
                      actions: [
                        TextButton(
                          onPressed: () => Navigator.pop(context),
                          child: const Text('Cancel'),
                        ),
                        TextButton(
                          onPressed: () {
                            settingsProvider.resetSettings();
                            Navigator.pop(context);
                            ScaffoldMessenger.of(context).showSnackBar(
                              const SnackBar(content: Text('Settings reset')),
                            );
                          },
                          child: const Text('Reset'),
                        ),
                      ],
                    ),
                  );
                },
                icon: const Icon(Icons.refresh),
                label: const Text('Reset Settings'),
                style: ElevatedButton.styleFrom(
                  backgroundColor: Colors.red,
                  foregroundColor: Colors.white,
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}

class _SettingSection extends StatelessWidget {
  final String title;
  final List<Widget> children;

  const _SettingSection({
    required this.title,
    required this.children,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          title,
          style: Theme.of(context).textTheme.titleMedium?.copyWith(
                fontWeight: FontWeight.bold,
              ),
        ),
        const SizedBox(height: 12),
        Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            border: Border.all(color: Colors.grey.withOpacity(0.3)),
            borderRadius: BorderRadius.circular(12),
          ),
          child: Column(children: children),
        ),
      ],
    );
  }
}

class _SettingTextField extends StatelessWidget {
  final String label;
  final TextEditingController controller;
  final Function(String) onChanged;
  final String hint;
  final bool obscureText;

  const _SettingTextField({
    required this.label,
    required this.controller,
    required this.onChanged,
    required this.hint,
    this.obscureText = false,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: const TextStyle(fontWeight: FontWeight.w500)),
        const SizedBox(height: 8),
        TextField(
          controller: controller,
          obscureText: obscureText,
          onChanged: onChanged,
          decoration: InputDecoration(
            hintText: hint,
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(8),
            ),
          ),
        ),
      ],
    );
  }
}

class _SettingSwitch extends StatelessWidget {
  final String label;
  final bool value;
  final Function(bool) onChanged;

  const _SettingSwitch({
    required this.label,
    required this.value,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Text(label),
        Switch(value: value, onChanged: onChanged),
      ],
    );
  }
}

class _SettingSlider extends StatelessWidget {
  final String label;
  final double value;
  final Function(double) onChanged;
  final double min;
  final double max;

  const _SettingSlider({
    required this.label,
    required this.value,
    required this.onChanged,
    required this.min,
    required this.max,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label),
        const SizedBox(height: 8),
        Slider(
          value: value,
          onChanged: onChanged,
          min: min,
          max: max,
          divisions: 10,
          label: value.toStringAsFixed(1),
        ),
      ],
    );
  }
}
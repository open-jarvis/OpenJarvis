import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/jarvis_provider.dart';

class ChatScreen extends StatefulWidget {
  const ChatScreen({Key? key}) : super(key: key);

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final TextEditingController _textController = TextEditingController();
  final ScrollController _scrollController = ScrollController();

  @override
  void dispose() {
    _textController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  void _scrollToBottom() {
    Future.delayed(const Duration(milliseconds: 100), () {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<JarvisProvider>(
      builder: (context, jarvisProvider, _) {
        return Scaffold(
          appBar: AppBar(
            title: const Text('OpenJarvis'),
            centerTitle: true,
            elevation: 0,
            actions: [
              Padding(
                padding: const EdgeInsets.all(16.0),
                child: Center(
                  child: jarvisProvider.isLoading
                      ? const SizedBox(
                          width: 20,
                          height: 20,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const SizedBox.shrink(),
                ),
              ),
            ],
          ),
          body: Column(
            children: [
              // Messages list
              Expanded(
                child: jarvisProvider.messages.isEmpty
                    ? Center(
                        child: Column(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            Icon(
                              Icons.mic_none,
                              size: 64,
                              color: Colors.grey.withOpacity(0.5),
                            ),
                            const SizedBox(height: 16),
                            Text(
                              'Press the mic to start',
                              style: Theme.of(context).textTheme.titleMedium?.copyWith(
                                    color: Colors.grey,
                                  ),
                            ),
                          ],
                        ),
                      )
                    : ListView.builder(
                        controller: _scrollController,
                        padding: const EdgeInsets.all(16),
                        itemCount: jarvisProvider.messages.length,
                        itemBuilder: (context, index) {
                          final message = jarvisProvider.messages[index];
                          return _MessageBubble(message: message);
                        },
                      ),
              ),
              // Error message
              if (jarvisProvider.error != null)
                Padding(
                  padding: const EdgeInsets.all(16.0),
                  child: Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: Colors.red.withOpacity(0.1),
                      border: Border.all(color: Colors.red),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Text(
                      jarvisProvider.error!,
                      style: const TextStyle(color: Colors.red),
                    ),
                  ),
                ),
              // Input area
              Padding(
                padding: MediaQuery.of(context).viewInsets,
                child: _InputArea(
                  textController: _textController,
                  onMessageSent: () {
                    if (_textController.text.isNotEmpty) {
                      jarvisProvider.sendMessage(_textController.text);
                      _textController.clear();
                      _scrollToBottom();
                    }
                  },
                  onVoiceStarted: () async {
                    await jarvisProvider.startVoiceInput();
                    _scrollToBottom();
                  },
                  onVoiceStopped: () async {
                    await jarvisProvider.stopVoiceInput();
                  },
                  isListening: jarvisProvider.isListening,
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}

class _MessageBubble extends StatelessWidget {
  final Message message;

  const _MessageBubble({required this.message});

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: message.isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.only(bottom: 12),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        decoration: BoxDecoration(
          color: message.isUser
              ? Theme.of(context).colorScheme.primary
              : Theme.of(context).colorScheme.surfaceVariant,
          borderRadius: BorderRadius.circular(16),
        ),
        constraints: BoxConstraints(
          maxWidth: MediaQuery.of(context).size.width * 0.75,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              message.text,
              style: TextStyle(
                color: message.isUser ? Colors.white : Colors.black87,
              ),
            ),
            const SizedBox(height: 4),
            Text(
              _formatTime(message.timestamp),
              style: TextStyle(
                fontSize: 12,
                color: message.isUser
                    ? Colors.white.withOpacity(0.7)
                    : Colors.black54,
              ),
            ),
          ],
        ),
      ),
    );
  }

  String _formatTime(DateTime time) {
    return '${time.hour}:${time.minute.toString().padLeft(2, '0')}';
  }
}

class _InputArea extends StatelessWidget {
  final TextEditingController textController;
  final VoidCallback onMessageSent;
  final VoidCallback onVoiceStarted;
  final VoidCallback onVoiceStopped;
  final bool isListening;

  const _InputArea({
    required this.textController,
    required this.onMessageSent,
    required this.onVoiceStarted,
    required this.onVoiceStopped,
    required this.isListening,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        border: Border(
          top: BorderSide(
            color: Colors.grey.withOpacity(0.2),
          ),
        ),
      ),
      child: Row(
        children: [
          Expanded(
            child: TextField(
              controller: textController,
              decoration: InputDecoration(
                hintText: 'Type a message...',
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(24),
                ),
                contentPadding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
              ),
              maxLines: null,
            ),
          ),
          const SizedBox(width: 12),
          FloatingActionButton(
            onPressed: onMessageSent,
            mini: true,
            child: const Icon(Icons.send),
          ),
          const SizedBox(width: 12),
          FloatingActionButton(
            onPressed: isListening ? onVoiceStopped : onVoiceStarted,
            mini: true,
            backgroundColor: isListening ? Colors.red : null,
            child: Icon(isListening ? Icons.mic : Icons.mic_none),
          ),
        ],
      ),
    );
  }
}
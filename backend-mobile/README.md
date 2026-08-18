# OpenJarvis Mobile Backend

A lightweight, mobile-optimized backend for the OpenJarvis mobile app. Built with Express.js and WebSocket support for real-time communication.

## Features

✨ **Real-time Communication**
- WebSocket support for instant messaging
- Bi-directional streaming
- Automatic reconnection handling

🤖 **Multi-LLM Support**
- Anthropic Claude (Haiku, Sonnet, Opus)
- OpenAI GPT-4 / GPT-3.5
- Groq (ultra-fast inference)
- Local Ollama models

💾 **Conversation Management**
- Per-conversation history
- User session tracking
- Automatic cleanup

🔒 **Security**
- API key authentication
- CORS configuration
- Input validation

📊 **Monitoring**
- Comprehensive logging (Winston)
- Health check endpoint
- Performance metrics

## Quick Start

### Prerequisites
- Node.js 18+
- npm or yarn
- API key for at least one LLM provider

### Installation

1. **Clone and navigate to backend**
   ```bash
   cd backend-mobile
   ```

2. **Install dependencies**
   ```bash
   npm install
   ```

3. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your API keys
   ```

4. **Start development server**
   ```bash
   npm run dev
   ```

   Or build and start production:
   ```bash
   npm run build
   npm start
   ```

## Configuration

### Environment Variables

```env
# Server
PORT=8000
NODE_ENV=development
LOG_LEVEL=info

# LLM Provider (choose one)
LLM_PROVIDER=claude          # Options: claude, openai, groq, local
LLM_MODEL=claude-3-haiku-20240307

# API Keys
CLAUDE_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GROQ_API_KEY=gsk_...

# Local Ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=mistral

# CORS
CORS_ORIGIN=*
```

## API Endpoints

### Health Check
```bash
GET /health
```

Response:
```json
{
  "status": "ok",
  "timestamp": "2024-08-18T10:30:00Z",
  "llmProvider": "claude"
}
```

### REST Chat Endpoint
```bash
POST /api/chat
Headers:
  X-API-Key: your-api-key
  X-User-Id: user-123
Body:
{
  "message": "Hello Jarvis!",
  "conversationId": "optional-conv-id"
}
```

Response:
```json
{
  "message": "Hello! How can I help you?",
  "conversationId": "conv-123",
  "model": "claude-3-haiku-20240307",
  "tokensUsed": 45
}
```

### WebSocket Connection

**Connect:**
```bash
ws://localhost:8000/ws
```

**Send Message:**
```json
{
  "type": "query",
  "text": "What's the weather?",
  "conversationId": "optional-conv-id"
}
```

**Receive Response:**
```json
{
  "type": "response",
  "text": "I don't have real-time weather data...",
  "conversationId": "conv-123",
  "timestamp": "2024-08-18T10:30:00Z"
}
```

**Thinking State:**
```json
{
  "type": "thinking",
  "text": "Processing your request..."
}
```

**Error:**
```json
{
  "type": "error",
  "message": "Failed to process message"
}
```

## Message Types

### Client → Server
- **query**: Text-based question/command
- **voice**: Audio data for speech-to-text (base64)
- **auth**: Authentication (optional)

### Server → Client
- **response**: LLM response to user query
- **thinking**: Intermediate processing status
- **error**: Error notification

## Project Structure

```
backend-mobile/
├── src/
│   ├── server.ts              # Express server & WebSocket setup
│   ├── services/
│   │   ├── llm.ts             # LLM integration service
│   │   ├── websocket.ts       # WebSocket connection manager
│   │   └── conversation.ts    # Conversation history management
│   ├── middleware/
│   │   ├── auth.ts            # API authentication
│   │   └── errorHandler.ts    # Global error handler
│   └── utils/
│       └── logger.ts          # Winston logging setup
├── package.json
├── tsconfig.json
├── .env.example
└── README.md
```

## Choosing an LLM Provider

### Claude (Recommended)
- Best balance of speed and quality
- Cheaper than GPT-4
- Haiku model (fastest)

```bash
LLM_PROVIDER=claude
LLM_MODEL=claude-3-haiku-20240307
CLAUDE_API_KEY=sk-ant-...
```

### OpenAI
- Most capable (GPT-4)
- Higher cost
- Widely supported

```bash
LLM_PROVIDER=openai
LLM_MODEL=gpt-4-turbo
OPENAI_API_KEY=sk-...
```

### Groq
- Extremely fast inference
- Free tier available
- Great for real-time apps

```bash
LLM_PROVIDER=groq
LLM_MODEL=mixtral-8x7b-32768
GROQ_API_KEY=gsk_...
```

### Local Ollama
- Run locally (privacy)
- No API costs
- Lower latency

```bash
LLM_PROVIDER=local
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=mistral
```

## Deployment

### Docker

```dockerfile
FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm ci --only=production
COPY . .
RUN npm run build
EXPOSE 8000
CMD ["npm", "start"]
```

### Environment Setup

```bash
# Build
npm run build

# Set environment variables
export NODE_ENV=production
export LLM_PROVIDER=claude
export CLAUDE_API_KEY=sk-ant-...

# Run
npm start
```

## Development

### Watch Mode
```bash
npm run dev
```

### Linting
```bash
npm run lint
```

### Testing
```bash
npm test
```

## Performance Tips

1. **Use Haiku for speed**: Claude Haiku is faster and cheaper for mobile
2. **Enable streaming**: For large responses, use streaming APIs
3. **Cache responses**: Consider caching common queries
4. **Connection pooling**: Reuse WebSocket connections
5. **Rate limiting**: Implement rate limiting for production

## Troubleshooting

### WebSocket Connection Failed
- Verify server is running: `curl http://localhost:8000/health`
- Check firewall/proxy settings
- Ensure CORS is configured correctly

### API Key Errors
- Verify API key is correct
- Check provider is spelled correctly
- Ensure API key has necessary permissions

### Slow Responses
- Switch to faster model (Haiku, Mixtral)
- Check network latency
- Monitor server CPU/memory usage

## Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Submit a pull request

## License

Apache 2.0 - See [LICENSE](../LICENSE)

## Support

- **Discord**: [discord.gg/CMVBmDQ5Fj](https://discord.gg/CMVBmDQ5Fj)
- **Issues**: [GitHub Issues](https://github.com/open-jarvis/OpenJarvis/issues)
- **Docs**: [open-jarvis.github.io](https://open-jarvis.github.io/OpenJarvis/)

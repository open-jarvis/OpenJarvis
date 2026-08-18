import express, { Express, Request, Response } from 'express';
import expressWs from 'express-ws';
import cors from 'cors';
import bodyParser from 'body-parser';
import dotenv from 'dotenv';
import { v4 as uuidv4 } from 'uuid';
import logger from './utils/logger';
import { WebSocketManager } from './services/websocket';
import { LLMService } from './services/llm';
import { ConversationService } from './services/conversation';
import authMiddleware from './middleware/auth';
import errorHandler from './middleware/errorHandler';

dotenv.config();

const app: Express = express();
const port = process.env.PORT || 8000;

// Middleware
app.use(cors({ origin: process.env.CORS_ORIGIN || '*' }));
app.use(bodyParser.json({ limit: '10mb' }));
app.use(bodyParser.urlencoded({ limit: '10mb', extended: true }));

// Initialize WebSocket
const { app: wsApp, getWss } = expressWs(app);

// Services
const wsManager = new WebSocketManager();
const llmService = new LLMService();
const conversationService = new ConversationService();

// Health check
app.get('/health', (req: Request, res: Response) => {
  res.json({
    status: 'ok',
    timestamp: new Date().toISOString(),
    llmProvider: process.env.LLM_PROVIDER || 'unknown',
  });
});

// REST API endpoints
app.post('/api/chat', authMiddleware, async (req: Request, res: Response) => {
  try {
    const { message, conversationId } = req.body;
    const userId = (req as any).userId;

    if (!message) {
      return res.status(400).json({ error: 'Message is required' });
    }

    const response = await llmService.chat(message, {
      conversationId: conversationId || uuidv4(),
      userId,
    });

    res.json(response);
  } catch (error) {
    logger.error('Chat endpoint error:', error);
    res.status(500).json({ error: 'Failed to process message' });
  }
});

// WebSocket endpoint
(wsApp as any).ws('/ws', (ws: any, req: Request) => {
  const clientId = uuidv4();
  const userId = (req as any).userId || 'anonymous';

  logger.info(`WebSocket client connected: ${clientId}`);
  wsManager.addClient(clientId, ws, userId);

  ws.on('message', async (msg: string) => {
    try {
      const data = JSON.parse(msg);
      logger.debug(`Message from ${clientId}:`, data);

      switch (data.type) {
        case 'auth':
          // Authentication is typically done via HTTP headers
          ws.send(JSON.stringify({ type: 'auth_response', success: true }));
          break;

        case 'query':
          await handleQuery(clientId, data, ws);
          break;

        case 'voice':
          await handleVoice(clientId, data, ws);
          break;

        default:
          ws.send(
            JSON.stringify({ type: 'error', message: 'Unknown message type' })
          );
      }
    } catch (error) {
      logger.error(`Error processing message from ${clientId}:`, error);
      ws.send(
        JSON.stringify({
          type: 'error',
          message: 'Failed to process message',
        })
      );
    }
  });

  ws.on('close', () => {
    logger.info(`WebSocket client disconnected: ${clientId}`);
    wsManager.removeClient(clientId);
  });

  ws.on('error', (error: Error) => {
    logger.error(`WebSocket error for ${clientId}:`, error);
    wsManager.removeClient(clientId);
  });
});

async function handleQuery(clientId: string, data: any, ws: any) {
  const { text, conversationId } = data;

  if (!text) {
    ws.send(JSON.stringify({ type: 'error', message: 'Text is required' }));
    return;
  }

  try {
    // Send thinking status
    ws.send(
      JSON.stringify({
        type: 'thinking',
        text: 'Processing your request...',
      })
    );

    // Get LLM response with streaming
    const response = await llmService.chat(text, {
      conversationId: conversationId || uuidv4(),
      userId: wsManager.getUserId(clientId),
    });

    // Send response
    ws.send(
      JSON.stringify({
        type: 'response',
        text: response.message,
        conversationId: response.conversationId,
        timestamp: new Date().toISOString(),
      })
    );
  } catch (error) {
    logger.error('Query handling error:', error);
    ws.send(
      JSON.stringify({
        type: 'error',
        message: 'Failed to process query',
      })
    );
  }
}

async function handleVoice(clientId: string, data: any, ws: any) {
  const { data: audioData, conversationId } = data;

  if (!audioData) {
    ws.send(JSON.stringify({ type: 'error', message: 'Audio data is required' }));
    return;
  }

  try {
    ws.send(
      JSON.stringify({
        type: 'thinking',
        text: 'Processing your voice...',
      })
    );

    // TODO: Implement speech-to-text using Whisper API or local STT
    // For now, send a placeholder response
    ws.send(
      JSON.stringify({
        type: 'response',
        text: 'Voice processing not yet implemented. Please use text input.',
        conversationId: conversationId || uuidv4(),
        timestamp: new Date().toISOString(),
      })
    );
  } catch (error) {
    logger.error('Voice handling error:', error);
    ws.send(
      JSON.stringify({
        type: 'error',
        message: 'Failed to process voice',
      })
    );
  }
}

// Error handling middleware
app.use(errorHandler);

// Start server
app.listen(port, () => {
  logger.info(`🚀 Server running on http://localhost:${port}`);
  logger.info(`📊 LLM Provider: ${process.env.LLM_PROVIDER || 'claude'}`);
  logger.info(`🔌 WebSocket ready at ws://localhost:${port}/ws`);
});

export default app;

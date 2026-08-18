import Anthropic from '@anthropic-ai/sdk';
import OpenAI from 'openai';
import Groq from 'groq-sdk';
import logger from '../utils/logger';

export interface ChatOptions {
  conversationId: string;
  userId: string;
}

export interface ChatResponse {
  message: string;
  conversationId: string;
  model: string;
  tokensUsed?: number;
}

export class LLMService {
  private anthropic: Anthropic | null = null;
  private openai: OpenAI | null = null;
  private groq: Groq | null = null;
  private provider: string;
  private model: string;
  private conversationHistory: Map<string, any[]> = new Map();

  constructor() {
    this.provider = process.env.LLM_PROVIDER || 'claude';
    this.model = process.env.LLM_MODEL || 'claude-3-haiku-20240307';

    this.initializeProvider();
  }

  private initializeProvider() {
    switch (this.provider) {
      case 'anthropic':
      case 'claude':
        if (!process.env.CLAUDE_API_KEY) {
          throw new Error('CLAUDE_API_KEY not set');
        }
        this.anthropic = new Anthropic({
          apiKey: process.env.CLAUDE_API_KEY,
        });
        logger.info('✅ Anthropic Claude initialized');
        break;

      case 'openai':
        if (!process.env.OPENAI_API_KEY) {
          throw new Error('OPENAI_API_KEY not set');
        }
        this.openai = new OpenAI({
          apiKey: process.env.OPENAI_API_KEY,
        });
        logger.info('✅ OpenAI initialized');
        break;

      case 'groq':
        if (!process.env.GROQ_API_KEY) {
          throw new Error('GROQ_API_KEY not set');
        }
        this.groq = new Groq({
          apiKey: process.env.GROQ_API_KEY,
        });
        logger.info('✅ Groq initialized');
        break;

      default:
        throw new Error(`Unsupported LLM provider: ${this.provider}`);
    }
  }

  async chat(message: string, options: ChatOptions): Promise<ChatResponse> {
    const { conversationId, userId } = options;

    // Get conversation history
    const history = this.conversationHistory.get(conversationId) || [];

    try {
      let response: string;
      let tokensUsed: number | undefined;

      switch (this.provider) {
        case 'anthropic':
        case 'claude':
          ({ response, tokensUsed } = await this.claudeChat(
            message,
            history
          ));
          break;

        case 'openai':
          ({ response, tokensUsed } = await this.openaiChat(
            message,
            history
          ));
          break;

        case 'groq':
          ({ response, tokensUsed } = await this.groqChat(message, history));
          break;

        default:
          throw new Error(`Unsupported provider: ${this.provider}`);
      }

      // Store in conversation history
      history.push({ role: 'user', content: message });
      history.push({ role: 'assistant', content: response });
      this.conversationHistory.set(conversationId, history);

      logger.info(`Chat response generated (${this.provider})`);

      return {
        message: response,
        conversationId,
        model: this.model,
        tokensUsed,
      };
    } catch (error) {
      logger.error(`LLM error (${this.provider}):`, error);
      throw error;
    }
  }

  private async claudeChat(
    message: string,
    history: any[]
  ): Promise<{ response: string; tokensUsed?: number }> {
    if (!this.anthropic) {
      throw new Error('Anthropic not initialized');
    }

    const response = await this.anthropic.messages.create({
      model: this.model,
      max_tokens: 1024,
      system:
        'You are Jarvis, a helpful personal AI assistant. Be concise and friendly.',
      messages: history.map((msg) => ({
        role: msg.role,
        content: msg.content,
      })),
    });

    const text =
      response.content[0].type === 'text' ? response.content[0].text : '';

    return {
      response: text,
      tokensUsed: response.usage?.input_tokens + response.usage?.output_tokens,
    };
  }

  private async openaiChat(
    message: string,
    history: any[]
  ): Promise<{ response: string; tokensUsed?: number }> {
    if (!this.openai) {
      throw new Error('OpenAI not initialized');
    }

    const response = await this.openai.chat.completions.create({
      model: this.model,
      max_tokens: 1024,
      system:
        'You are Jarvis, a helpful personal AI assistant. Be concise and friendly.',
      messages: history.map((msg) => ({
        role: msg.role as 'user' | 'assistant',
        content: msg.content,
      })),
    });

    const text = response.choices[0].message.content || '';

    return {
      response: text,
      tokensUsed: response.usage?.total_tokens,
    };
  }

  private async groqChat(
    message: string,
    history: any[]
  ): Promise<{ response: string; tokensUsed?: number }> {
    if (!this.groq) {
      throw new Error('Groq not initialized');
    }

    const response = await this.groq.chat.completions.create({
      model: this.model,
      max_tokens: 1024,
      messages: [
        {
          role: 'system',
          content:
            'You are Jarvis, a helpful personal AI assistant. Be concise and friendly.',
        },
        ...history.map((msg) => ({
          role: msg.role as 'user' | 'assistant',
          content: msg.content,
        })),
      ],
    });

    const text = response.choices[0].message.content || '';

    return {
      response: text,
      tokensUsed: response.usage?.total_tokens,
    };
  }

  // Clear conversation history
  clearHistory(conversationId: string) {
    this.conversationHistory.delete(conversationId);
  }
}

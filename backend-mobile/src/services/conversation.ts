import logger from '../utils/logger';

interface ConversationMessage {
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
}

interface Conversation {
  id: string;
  userId: string;
  messages: ConversationMessage[];
  createdAt: Date;
  updatedAt: Date;
}

export class ConversationService {
  private conversations: Map<string, Conversation> = new Map();

  createConversation(conversationId: string, userId: string): Conversation {
    const conversation: Conversation = {
      id: conversationId,
      userId,
      messages: [],
      createdAt: new Date(),
      updatedAt: new Date(),
    };

    this.conversations.set(conversationId, conversation);
    logger.info(`Created conversation: ${conversationId}`);
    return conversation;
  }

  getConversation(conversationId: string): Conversation | undefined {
    return this.conversations.get(conversationId);
  }

  addMessage(
    conversationId: string,
    role: 'user' | 'assistant',
    content: string
  ) {
    const conversation = this.conversations.get(conversationId);
    if (!conversation) {
      throw new Error(`Conversation not found: ${conversationId}`);
    }

    conversation.messages.push({
      role,
      content,
      timestamp: new Date(),
    });

    conversation.updatedAt = new Date();
  }

  deleteConversation(conversationId: string): boolean {
    return this.conversations.delete(conversationId);
  }

  getUserConversations(userId: string): Conversation[] {
    return Array.from(this.conversations.values()).filter(
      (conv) => conv.userId === userId
    );
  }
}

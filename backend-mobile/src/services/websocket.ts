import logger from '../utils/logger';

interface Client {
  ws: any;
  userId: string;
  connectedAt: Date;
}

export class WebSocketManager {
  private clients: Map<string, Client> = new Map();

  addClient(clientId: string, ws: any, userId: string) {
    this.clients.set(clientId, {
      ws,
      userId,
      connectedAt: new Date(),
    });
    logger.info(`Added WebSocket client: ${clientId} (user: ${userId})`);
  }

  removeClient(clientId: string) {
    this.clients.delete(clientId);
    logger.info(`Removed WebSocket client: ${clientId}`);
  }

  getClient(clientId: string) {
    return this.clients.get(clientId);
  }

  getUserId(clientId: string): string {
    return this.clients.get(clientId)?.userId || 'anonymous';
  }

  broadcast(message: any) {
    const msg = JSON.stringify(message);
    this.clients.forEach((client) => {
      try {
        client.ws.send(msg);
      } catch (error) {
        logger.error('Error broadcasting to client:', error);
      }
    });
  }

  broadcastToUser(userId: string, message: any) {
    const msg = JSON.stringify(message);
    this.clients.forEach((client) => {
      if (client.userId === userId) {
        try {
          client.ws.send(msg);
        } catch (error) {
          logger.error('Error broadcasting to user:', error);
        }
      }
    });
  }

  getConnectedCount(): number {
    return this.clients.size;
  }
}

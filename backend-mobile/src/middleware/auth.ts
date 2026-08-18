import { Request, Response, NextFunction } from 'express';
import logger from '../utils/logger';

const authMiddleware = (req: Request, res: Response, next: NextFunction) => {
  // For development, we'll use a simple header-based auth
  // In production, use JWT or OAuth

  const apiKey = req.headers['x-api-key'];
  const userId = req.headers['x-user-id'];

  if (!apiKey) {
    logger.warn('Request without API key');
    return res.status(401).json({ error: 'API key required' });
  }

  // Validate API key (this is a simple example)
  if (apiKey !== process.env.OPENJARVIS_API_KEY && process.env.NODE_ENV === 'production') {
    logger.warn('Invalid API key');
    return res.status(401).json({ error: 'Invalid API key' });
  }

  // Attach userId to request
  (req as any).userId = userId || 'anonymous';

  next();
};

export default authMiddleware;

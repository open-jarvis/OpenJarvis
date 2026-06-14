import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { FavoriteButton } from '../FavoriteButton';

const mockFetchFavorites = vi.hoisted(() => vi.fn());
const mockToggleFavorite = vi.hoisted(() => vi.fn());

vi.mock('../../Desktop/lib/api', () => ({
  fetchFavorites: mockFetchFavorites,
  toggleFavorite: mockToggleFavorite,
}));

describe('FavoriteButton', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders unfilled star when not favorited', async () => {
    mockFetchFavorites.mockResolvedValue({ favorites: [] });
    render(<FavoriteButton toolName="nmap" />);

    await waitFor(() => {
      const btn = screen.getByRole('button');
      expect(btn).toHaveAttribute('title', 'Add to favorites');
    });
  });

  it('renders filled star when favorited', async () => {
    mockFetchFavorites.mockResolvedValue({ favorites: ['nmap'] });
    render(<FavoriteButton toolName="nmap" />);

    await waitFor(() => {
      const btn = screen.getByRole('button');
      expect(btn).toHaveAttribute('title', 'Remove from favorites');
    });
  });

  it('toggles favorite on click', async () => {
    mockFetchFavorites.mockResolvedValue({ favorites: [] });
    mockToggleFavorite.mockResolvedValue({ favorited: true });
    render(<FavoriteButton toolName="nmap" />);

    await waitFor(() => {
      expect(screen.getByRole('button')).toHaveAttribute('title', 'Add to favorites');
    });

    fireEvent.click(screen.getByRole('button'));

    await waitFor(() => {
      expect(screen.getByRole('button')).toHaveAttribute('title', 'Remove from favorites');
    });

    expect(mockToggleFavorite).toHaveBeenCalledWith(expect.any(String), 'nmap');
  });

  it('handles fetch error gracefully', async () => {
    mockFetchFavorites.mockRejectedValue(new Error('Network error'));
    render(<FavoriteButton toolName="nmap" />);

    await waitFor(() => {
      expect(screen.getByRole('button')).toBeInTheDocument();
    });

    expect(screen.getByRole('button')).toHaveAttribute('title', 'Add to favorites');
  });
});

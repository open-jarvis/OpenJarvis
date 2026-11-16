import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ fetchIdentity: vi.fn() }));
vi.mock('./analytics', () => ({ fetchAnalyticsIdentity: mocks.fetchIdentity }));
import { offerAnalyticsChoice } from './analytics-invitation';

const seenKey = 'openjarvis-analytics-choice-seen';
let stored: Map<string, string>;

beforeEach(() => {
  vi.resetAllMocks();
  stored = new Map();
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => stored.get(key) ?? null,
    setItem: (key: string, value: string) => stored.set(key, value),
  });
});
afterEach(() => vi.unstubAllGlobals());

const invitation = (sharingModalSeen: boolean) => ({
  ready: false,
  sharingModalSeen,
  open: vi.fn(),
  markSharingModalSeen: vi.fn(),
});

describe('analytics invitation after setup', () => {
  it('does not consume a fresh user invitation while setup is incomplete', () => {
    const request = invitation(false);
    offerAnalyticsChoice(request);
    expect(request.open).not.toHaveBeenCalled();
    expect(request.markSharingModalSeen).not.toHaveBeenCalled();
    expect(stored.has(seenKey)).toBe(false);
    expect(mocks.fetchIdentity).not.toHaveBeenCalled();

    offerAnalyticsChoice({ ...request, ready: true });
    expect(request.open).toHaveBeenCalledOnce();
    expect(request.markSharingModalSeen).toHaveBeenCalledOnce();
    expect(stored.get(seenKey)).toBe('true');
  });

  it('waits for the desktop backend before checking an existing user choice', async () => {
    const request = invitation(true);
    offerAnalyticsChoice(request);
    expect(mocks.fetchIdentity).not.toHaveBeenCalled();
    expect(stored.has(seenKey)).toBe(false);

    mocks.fetchIdentity.mockResolvedValue({ choice_recorded: false });
    offerAnalyticsChoice({ ...request, ready: true });
    await vi.waitFor(() => expect(request.open).toHaveBeenCalledOnce());
    expect(stored.get(seenKey)).toBe('true');
  });

  it('does not reopen for an existing user who already recorded a choice', async () => {
    const request = invitation(true);
    mocks.fetchIdentity.mockResolvedValue({ choice_recorded: true });
    offerAnalyticsChoice({ ...request, ready: true });
    await vi.waitFor(() => expect(stored.get(seenKey)).toBe('true'));
    expect(request.open).not.toHaveBeenCalled();
  });

  it('does not consume the invitation when its effect is cancelled', async () => {
    const request = invitation(true);
    let finish: (identity: { choice_recorded: boolean }) => void = () => {};
    mocks.fetchIdentity.mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    const cancel = offerAnalyticsChoice({ ...request, ready: true });
    cancel?.();
    finish({ choice_recorded: false });
    await Promise.resolve();
    expect(request.open).not.toHaveBeenCalled();
    expect(stored.has(seenKey)).toBe(false);
  });

  it('keeps a failed lookup eligible for the next ready launch', async () => {
    const request = invitation(true);
    mocks.fetchIdentity.mockRejectedValueOnce(new Error('Server unavailable'));
    offerAnalyticsChoice({ ...request, ready: true });
    await Promise.resolve();
    await Promise.resolve();
    expect(stored.has(seenKey)).toBe(false);

    mocks.fetchIdentity.mockResolvedValue({ choice_recorded: false });
    offerAnalyticsChoice({ ...request, ready: true });
    await vi.waitFor(() => expect(request.open).toHaveBeenCalledOnce());
    expect(stored.get(seenKey)).toBe('true');
  });
});

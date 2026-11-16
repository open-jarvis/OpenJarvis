import { fetchAnalyticsIdentity } from './analytics';

const ANALYTICS_SEEN_KEY = 'openjarvis-analytics-choice-seen';

interface AnalyticsInvitation {
  ready: boolean;
  sharingModalSeen: boolean;
  open: () => void;
  markSharingModalSeen: () => void;
}

/** Offer the sharing dialog only after the app can actually display it. */
export function offerAnalyticsChoice({
  ready, sharingModalSeen, open, markSharingModalSeen,
}: AnalyticsInvitation): (() => void) | undefined {
  if (!ready) return;
  if (!sharingModalSeen) {
    open();
    markSharingModalSeen();
    localStorage.setItem(ANALYTICS_SEEN_KEY, 'true');
    return;
  }
  if (localStorage.getItem(ANALYTICS_SEEN_KEY)) return;

  // Existing users may have seen the older leaderboard-only dialog.
  let active = true;
  fetchAnalyticsIdentity().then((identity) => {
    if (!active) return;
    if (!identity.choice_recorded) open();
    localStorage.setItem(ANALYTICS_SEEN_KEY, 'true');
  }).catch(() => { /* Retry next launch if the server was unavailable. */ });
  return () => { active = false; };
}

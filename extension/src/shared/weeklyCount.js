/**
 * "Applications tailored this week" — the retention loop shown on Screen 1
 * (idle) and, once built, Screens 7/12 (success). Persisted in
 * chrome.storage.local (survives browser restarts, same tier as the
 * profile) rather than chrome.storage.session, since the whole point is
 * that it outlives any single tab.
 *
 * The week resets Monday 00:00 local time. There's no alarm or cron for
 * this — the stored { count, weekStart } is just compared against the
 * current week's start on every read, so a stale record silently reads
 * back as 0 without needing a background job to "do" the reset.
 *
 * Only "Download resume" increments it today (review/index.js) — the
 * design's other trigger, a submitted autofill, doesn't exist yet
 * (screens 5's autofill half / 6 / 7 are deferred).
 */

import { StorageKey } from "./constants.js";

/** Start of the current week (Monday 00:00) as a local-time ms timestamp. Exported for tests. */
export function currentWeekStart() {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  const day = d.getDay(); // 0 = Sunday .. 6 = Saturday
  const diff = (day === 0 ? -6 : 1) - day; // days back to this week's Monday
  d.setDate(d.getDate() + diff);
  return d.getTime();
}

/** Current count, or 0 if nothing's been recorded yet or the stored record is from a past week. */
export async function loadWeeklyCount() {
  const stored = await chrome.storage.local.get(StorageKey.WEEKLY_COUNT);
  const record = stored[StorageKey.WEEKLY_COUNT];
  if (!record || record.weekStart !== currentWeekStart()) return 0;
  return record.count;
}

/** Increment (starting a fresh week at 1 if the stored record is stale) and persist. Returns the new count. */
export async function incrementWeeklyCount() {
  const weekStart = currentWeekStart();
  const stored = await chrome.storage.local.get(StorageKey.WEEKLY_COUNT);
  const record = stored[StorageKey.WEEKLY_COUNT];
  const current = record && record.weekStart === weekStart ? record.count : 0;
  const count = current + 1;
  await chrome.storage.local.set({ [StorageKey.WEEKLY_COUNT]: { count, weekStart } });
  return count;
}

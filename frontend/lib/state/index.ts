const STATE_REVISION_KEY = "meeting_room_frontend_state_revision";

export function readStateRevision(): number {
  if (typeof window === "undefined") {
    return 0;
  }
  const value = window.localStorage.getItem(STATE_REVISION_KEY);
  return value ? Number(value) : 0;
}

export function writeStateRevision(revision: number) {
  if (typeof window !== "undefined") {
    window.localStorage.setItem(STATE_REVISION_KEY, String(revision));
  }
}

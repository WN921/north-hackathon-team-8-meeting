import { writeStateRevision } from "@/lib/state";

export type SuccessResponse<T = unknown> = {
  ok: true;
  request_id: string;
  data: T;
  warnings: string[];
  meta: ApiMeta;
};

export type ErrorResponse = {
  ok: false;
  request_id: string;
  error: {
    code: string;
    message: string;
    details?: unknown;
    suggestions?: string[];
    [key: string]: unknown;
  };
  warnings: string[];
  meta: ApiMeta;
};

export type ApiResponse<T = unknown> = SuccessResponse<T> | ErrorResponse;

export type ApiMeta = {
  state_revision: number;
  server_time: string;
  timezone: string;
};

export type User = {
  id: string;
  name: string;
  role: string;
};

export type Position = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export type Room = {
  id: string;
  name: string;
  type: string;
  location: string;
  capacity: number;
  equipment: string[];
  position: Position | null;
  status: string;
  protected: boolean;
  active?: boolean;
};

export type CompositeRoom = {
  id: string;
  name: string;
  member_room_ids: string[];
  capacity: number;
  equipment: string[];
  position: Position | null;
  status: string;
  protected: boolean;
};

export type Rule = {
  id?: string;
  rule_id?: string;
  rule_type: string;
  target_type: string;
  target_id: string;
  time_windows: Array<{ start_at: string; end_at: string; recurrence?: string | null }>;
  reason: string;
  fixed: boolean;
  editable: boolean;
  match_key?: string | null;
  created_by?: string;
  updated_by?: string;
};

export type Booking = {
  id?: string;
  booking_id?: string;
  target_type: string;
  target_id: string;
  start_at: string;
  end_at: string;
  title: string;
  organizer_id: string;
  attendees: string[];
  description?: string;
  status: string;
  created_at?: string;
  updated_at?: string;
};

export type CalendarSlot = {
  start_at: string;
  end_at: string;
  status: string;
  target_type?: string;
  target_id?: string;
  booking_id?: string;
  title?: string;
  rule_id?: string;
  reason_code?: string;
  message?: string;
};

export type AvailabilityTarget = {
  target_type: "room" | "composite";
  target_id: string;
  name: string;
  type?: string;
  capacity?: number;
  member_room_ids?: string[];
  available?: boolean;
  reason_code?: string;
  message?: string;
};

export type AvailabilityData = {
  available: boolean;
  checks: Array<{ check_type: string; passed: boolean }>;
  conflicts: unknown[];
  unavailable_reasons: Array<{ reason_code: string; message: string; rule_id?: string; conflicts?: unknown[] }>;
};

export type FloorPlanNode = {
  id: string;
  name: string;
  position: Position | null;
  status: string;
  reason_code?: string | null;
  message: string;
  member_room_ids?: string[];
};

export type FloorPlanData = {
  floor: {
    id: string;
    name: string;
  };
  rooms: FloorPlanNode[];
  composites: FloorPlanNode[];
  member_occupancies: unknown[];
};

export type LoginResponseData = {
  user: User;
  token: string;
};

export type RoomsData = {
  rooms: Room[];
  composites: CompositeRoom[];
};

export type RulesData = {
  items: Rule[];
};

export type BookingsData = {
  items: Booking[];
};

export type CalendarData = {
  slots: CalendarSlot[];
};

export type NLConfigureData = {
  intent: string;
  llm: { provider: string; model: string };
  parsed_changes: Array<{
    operation: string;
    target_type: string;
    target_id: string;
    rule_type: string;
    time_windows: Array<{ start_at: string; end_at: string; recurrence?: string | null }>;
    reason: string;
  }>;
  matched_rule_id?: string | null;
  rule_id: string;
  status: string;
  old_rule?: Rule | Record<string, never>;
  new_rule?: Rule;
  impacted_slots: unknown[];
  dry_run: boolean;
};

export type NLCandidatesData = {
  intent: string;
  llm: { provider: string; model: string };
  parsed_booking: {
    start_at: string;
    end_at: string;
    room_type: string;
    title: string;
  };
  candidates: AvailabilityTarget[];
  excluded_targets: AvailabilityTarget[];
};

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

const SESSION_KEY = "meeting_room_frontend_auth";

export type StoredAuth = {
  token: string;
  user: User;
};

export function readStoredAuth(): StoredAuth | null {
  if (typeof window === "undefined") {
    return null;
  }
  const raw = window.localStorage.getItem(SESSION_KEY);
  if (!raw) {
    return null;
  }
  try {
    return JSON.parse(raw) as StoredAuth;
  } catch {
    window.localStorage.removeItem(SESSION_KEY);
    return null;
  }
}

export function writeStoredAuth(auth: StoredAuth) {
  if (typeof window !== "undefined") {
    window.localStorage.setItem(SESSION_KEY, JSON.stringify(auth));
  }
}

export function clearStoredAuth() {
  if (typeof window !== "undefined") {
    window.localStorage.removeItem(SESSION_KEY);
  }
}

export function createIdempotencyKey(prefix: string) {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}

export function formatErrorMessage(error: unknown) {
  if (error instanceof ApiClientError) {
    const suggestions = error.response.error.suggestions?.join("；");
    return [error.response.error.message, error.response.error.code, suggestions].filter(Boolean).join("；");
  }
  return error instanceof Error ? error.message : "请求失败";
}

export class ApiClientError extends Error {
  constructor(public readonly response: ErrorResponse) {
    super(formatErrorResponse(response));
    this.name = "ApiClientError";
  }
}

export function formatErrorResponse(response: ErrorResponse) {
  const suggestions = response.error.suggestions?.join("；");
  return [response.error.message, response.error.code, suggestions].filter(Boolean).join("；");
}

export type RequestOptions = {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  token?: string | null;
  query?: Record<string, string | number | boolean | undefined>;
};

async function requestJson<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers({
    "Content-Type": "application/json",
  });

  if (options.token) {
    headers.set("Authorization", `Bearer ${options.token}`);
  }

  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(options.query ?? {})) {
    if (value !== undefined) {
      query.set(key, String(value));
    }
  }

  const url = `${API_BASE_URL}${path}${query.size ? `?${query.toString()}` : ""}`;
  const response = await fetch(url, {
    method: options.method ?? "GET",
    headers,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });

  const payload = (await response.json()) as ApiResponse<T>;
  if (!response.ok || payload.ok === false) {
    throw new ApiClientError(payload as ErrorResponse);
  }
  writeStateRevision(payload.meta.state_revision);
  return payload.data;
}

export const api = {
  login(username: string, password: string) {
    return requestJson<LoginResponseData>("/api/auth/login", {
      method: "POST",
      body: { username, password },
    });
  },

  logout(token: string) {
    return requestJson<Record<string, unknown>>("/api/auth/logout", {
      method: "POST",
      token,
    });
  },

  me(token: string) {
    return requestJson<{ user: User }>("/api/auth/me", { token });
  },

  listRooms(token: string, includeComposite = true) {
    return requestJson<RoomsData>("/api/rooms", {
      token,
      query: { include_composite: includeComposite },
    });
  },

  listBookings(token: string, query?: Record<string, string | undefined>) {
    return requestJson<BookingsData>("/api/bookings", { token, query });
  },

  getBooking(token: string, bookingId: string) {
    return requestJson<Booking>(`/api/bookings/${bookingId}`, { token });
  },

  createBooking(token: string, body: {
    workspace_id?: string;
    actor_id: string;
    idempotency_key: string;
    expected_state_revision: number;
    dry_run?: boolean;
    target_type: "room" | "composite";
    target_id: string;
    start_at: string;
    end_at: string;
    title: string;
    organizer_id: string;
    attendees?: string[];
    description?: string;
  }) {
    return requestJson<{ booking_id: string; status: string; target_type: string; target_id: string; conflicts: unknown[] }>("/api/bookings", {
      method: "POST",
      token,
      body,
    });
  },

  cancelBooking(token: string, bookingId: string, body: {
    workspace_id?: string;
    actor_id: string;
    idempotency_key: string;
    expected_state_revision: number;
    dry_run?: boolean;
    reason?: string;
  }) {
    return requestJson<{ booking_id: string; status: string; released_slots: unknown[] }>(`/api/bookings/${bookingId}/cancel`, {
      method: "POST",
      token,
      body,
    });
  },

  updateBooking(token: string, bookingId: string, body: {
    workspace_id?: string;
    actor_id: string;
    idempotency_key: string;
    expected_state_revision: number;
    dry_run?: boolean;
    title?: string;
    start_at?: string;
    end_at?: string;
    reason?: string;
  }) {
    return requestJson<{ booking_id: string; status: string; old_booking: Booking; new_booking: Booking; conflicts: unknown[] }>(`/api/bookings/${bookingId}`, {
      method: "PATCH",
      token,
      body,
    });
  },

  checkAvailability(token: string, body: {
    target_type: "room" | "composite";
    target_id: string;
    start_at: string;
    end_at: string;
    capacity?: number;
    equipment?: string[];
  }) {
    return requestJson<AvailabilityData>("/api/availability:check", {
      method: "POST",
      token,
      body,
    });
  },

  queryAvailability(token: string, body: {
    start_at: string;
    end_at: string;
    timezone?: string;
    capacity?: number;
    equipment?: string[];
    room_types?: string[];
    allow_merge?: boolean;
  }) {
    return requestJson<{ available_targets: AvailabilityTarget[]; unavailable_targets: AvailabilityTarget[]; conflicts: unknown[] }>("/api/availability:query", {
      method: "POST",
      token,
      body,
    });
  },

  getCalendar(token: string, query?: Record<string, string | undefined>) {
    return requestJson<CalendarData>("/api/calendar", { token, query });
  },

  listRules(token: string, query?: Record<string, string | undefined>) {
    return requestJson<RulesData>("/api/rules", { token, query });
  },

  configureNaturalLanguage(token: string, body: {
    utterance: string;
    workspace_id?: string;
    actor_id: string;
    dry_run?: boolean;
    idempotency_key: string;
    expected_state_revision: number;
  }) {
    return requestJson<NLConfigureData>("/api/nl/configure", {
      method: "POST",
      token,
      body,
    });
  },

  naturalLanguageCandidates(token: string, body: {
    utterance: string;
    workspace_id?: string;
    actor_id: string;
    dry_run?: boolean;
    idempotency_key: string;
    expected_state_revision: number;
  }) {
    return requestJson<NLCandidatesData>("/api/nl/bookings:candidates", {
      method: "POST",
      token,
      body,
    });
  },

  getFloorPlan(token: string, query?: Record<string, string | undefined>) {
    return requestJson<FloorPlanData>("/api/floor-plan", { token, query });
  },
};

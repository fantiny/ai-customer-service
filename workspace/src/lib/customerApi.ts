import { getStoredToken } from './auth';

const BASE = (import.meta.env.VITE_API_BASE_URL as string) || 'http://localhost:8000';

function authHeaders(): HeadersInit {
  const token = getStoredToken();
  return token ? { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' } : { 'Content-Type': 'application/json' };
}

export interface SessionSummary {
  session_id: string;
  mode: string;
  msg_count: number;
  first_content: string;
  last_content: string;
  created_at: string | null;
  updated_at: string | null;
}

export async function listMySessions(): Promise<SessionSummary[]> {
  const res = await fetch(`${BASE}/chat/sessions/mine`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`sessions/mine → ${res.status}`);
  return res.json();
}

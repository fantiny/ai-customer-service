import { getStoredToken } from './auth';
import type {
  KnowledgeDoc, BusinessRule, PromptHistory,
  TodayMetrics, AnalyticsData, Digest, SystemHealth, AdminChatMessage,
} from '../types';

const BASE = (import.meta.env.VITE_API_BASE_URL as string) || 'http://localhost:8000';

function authHeaders(): HeadersInit {
  const token = getStoredToken();
  return token ? { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' } : { 'Content-Type': 'application/json' };
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { headers: authHeaders(), ...init });
  if (!res.ok) throw new Error(`API ${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

// ── Knowledge Base ────────────────────────────────────────────────────────

export async function listKnowledgeDocs(): Promise<KnowledgeDoc[]> {
  return api<KnowledgeDoc[]>('/api/workspace/admin/knowledge');
}

export async function getKnowledgeDoc(docId: string): Promise<KnowledgeDoc> {
  return api<KnowledgeDoc>(`/api/workspace/admin/knowledge/${docId}`);
}

export async function createKnowledgeDoc(body: {
  title: string; content: string; category: string; knowledge_type?: string;
}): Promise<KnowledgeDoc> {
  return api<KnowledgeDoc>('/api/workspace/admin/knowledge', {
    method: 'POST', body: JSON.stringify(body),
  });
}

export async function updateKnowledgeDoc(docId: string, body: {
  title?: string; content?: string; category?: string;
}): Promise<KnowledgeDoc> {
  return api<KnowledgeDoc>(`/api/workspace/admin/knowledge/${docId}`, {
    method: 'PUT', body: JSON.stringify(body),
  });
}

export async function deleteKnowledgeDoc(docId: string): Promise<void> {
  await fetch(`${BASE}/api/workspace/admin/knowledge/${docId}`, {
    method: 'DELETE', headers: authHeaders(),
  });
}

export async function embedAllDocs(category?: string): Promise<{ embedded: number; total: number }> {
  const qs = category ? `?category=${encodeURIComponent(category)}` : '';
  return api<{ embedded: number; total: number }>(`/api/workspace/admin/knowledge/embed-all${qs}`, { method: 'POST' });
}

export async function embedSingleDoc(docId: string): Promise<void> {
  await api(`/api/workspace/admin/knowledge/${docId}/embed`, { method: 'POST' });
}

// ── Business Rules ────────────────────────────────────────────────────────

export async function listRules(): Promise<BusinessRule[]> {
  // API returns { rule_key: { value, description } } dict; normalize to array.
  const raw = await api<Record<string, { value: unknown; description: string }>>('/api/workspace/admin/rules');
  return Object.entries(raw).map(([rule_key, v]) => ({
    rule_key,
    rule_value: typeof v.value === 'string' ? v.value : JSON.stringify(v.value),
    description: v.description ?? '',
  }));
}

export async function updateRule(key: string, value: string, description?: string): Promise<void> {
  await api(`/api/workspace/admin/rules/${encodeURIComponent(key)}`, {
    method: 'PUT', body: JSON.stringify({ rule_key: key, rule_value: value, description: description ?? '' }),
  });
}

export async function deleteRule(key: string): Promise<void> {
  await api(`/api/workspace/admin/rules/${encodeURIComponent(key)}`, { method: 'DELETE' });
}

export interface RuleAuditEntry {
  log_id: number;
  operation: 'set' | 'delete';
  old_value: string | null;
  new_value: string | null;
  changed_at: string;
}

export async function getRuleHistory(key: string): Promise<{ rule_key: string; history: RuleAuditEntry[] }> {
  return api(`/api/workspace/admin/rules/${encodeURIComponent(key)}/history`);
}

// ── Node Prompts ──────────────────────────────────────────────────────────

export async function listPrompts(): Promise<{ node_name: string; version: number; preview: string }[]> {
  // API returns array directly
  return api<{ node_name: string; version: number; preview: string }[]>('/api/workspace/admin/prompts');
}

export async function getPromptHistory(node: string): Promise<PromptHistory> {
  return api<PromptHistory>(`/api/workspace/admin/prompts/${node}`);
}

export async function publishPrompt(node: string, content: string): Promise<{ prompt_id: string; version: number }> {
  return api<{ prompt_id: string; version: number }>(`/api/workspace/admin/prompts/${node}`, {
    method: 'POST', body: JSON.stringify({ content }),
  });
}

export async function activatePromptVersion(node: string, promptId: string): Promise<{ prompt_id: string; version: number }> {
  return api<{ prompt_id: string; version: number }>(`/api/workspace/admin/prompts/${node}/activate-version`, {
    method: 'POST', body: JSON.stringify({ prompt_id: promptId }),
  });
}

// ── Analytics & Metrics ───────────────────────────────────────────────────

export async function getTodayMetrics(): Promise<TodayMetrics> {
  return api<TodayMetrics>('/api/workspace/metrics/today');
}

export async function getAnalytics(days = 7): Promise<AnalyticsData> {
  return api<AnalyticsData>(`/api/workspace/analytics?days=${days}`);
}

// ── Digest ────────────────────────────────────────────────────────────────

export async function listDigests(days = 7): Promise<Digest[]> {
  return api<Digest[]>(`/api/workspace/admin/digest?days=${days}`);
}

export async function getDigest(date: string): Promise<Digest> {
  return api<Digest>(`/api/workspace/admin/digest/${date}`);
}

export async function generateDigest(date?: string): Promise<{ success: boolean; report_date: string }> {
  const qs = date ? `?report_date=${date}` : '';
  return api(`/api/workspace/admin/digest/generate${qs}`, { method: 'POST' });
}

// ── Products ──────────────────────────────────────────────────────────────────

export async function listProducts(): Promise<import('../types').ProductInfo[]> {
  return api('/api/workspace/admin/products');
}

export async function updateProduct(productId: string, body: Partial<import('../types').ProductInfo>): Promise<import('../types').ProductInfo> {
  return api(`/api/workspace/admin/products/${encodeURIComponent(productId)}`, {
    method: 'PUT', body: JSON.stringify(body),
  });
}

export async function createProduct(body: import('../types').ProductInfo): Promise<import('../types').ProductInfo> {
  return api('/api/workspace/admin/products', {
    method: 'POST', body: JSON.stringify(body),
  });
}

// ── Admin AI Chat ─────────────────────────────────────────────────────────

export async function sendAdminChat(message: string, threadId?: string): Promise<{ thread_id: string; reply: string }> {
  return api<{ thread_id: string; reply: string }>('/api/admin/chat', {
    method: 'POST', body: JSON.stringify({ message, thread_id: threadId }),
  });
}

export async function getAdminChatHistory(threadId: string): Promise<{ thread_id: string; messages: AdminChatMessage[] }> {
  return api(`/api/admin/chat/history/${threadId}`);
}

// ── System Health (via admin chat tool get_system_metrics proxy) ──────────
// We call get_system_metrics indirectly by fetching doc list + rules + prompts
// ── Agent Session Notes ───────────────────────────────────────────────────────
export async function addSessionNote(sessionId: string, content: string, agentId: string): Promise<{ success: boolean; message_id: string }> {
  return api<{ success: boolean; message_id: string }>(`/api/workspace/sessions/${sessionId}/notes`, {
    method: 'POST',
    body: JSON.stringify({ content, agent_id: agentId }),
  });
}

// ── Agent KB Search (non-admin, used in AgentWorkspace) ──────────────────────
export interface KBSearchResult {
  doc_id: string;
  title: string;
  knowledge_type: 'business_policy' | 'industry_knowledge';
  snippet: string;
  score: number | null;
}

export async function agentKnowledgeSearch(q: string): Promise<KBSearchResult[]> {
  const res = await api<{ results: KBSearchResult[] }>(
    `/api/workspace/knowledge/search?q=${encodeURIComponent(q)}`
  );
  return res.results;
}

export async function getSystemHealth(): Promise<SystemHealth> {
  const [docs, rules, prompts, metrics, products] = await Promise.all([
    listKnowledgeDocs().catch(() => [] as KnowledgeDoc[]),
    listRules().catch(() => [] as BusinessRule[]),
    listPrompts().catch(() => [] as { node_name: string }[]),
    getTodayMetrics().catch(() => null),
    listProducts().catch(() => [] as import('../types').ProductInfo[]),
  ]);
  const withEmb = docs.filter(d => d.has_embedding).length;
  return {
    total_documents: docs.length,
    with_embedding: withEmb,
    embedding_coverage: docs.length > 0 ? Math.round((withEmb / docs.length) * 100) : 0,
    business_policy_count: docs.filter(d => d.knowledge_type === 'business_policy').length,
    industry_knowledge_count: docs.filter(d => d.knowledge_type === 'industry_knowledge').length,
    business_rules_count: rules.length,
    products_count: products.length,
    active_sessions: metrics?.total_sessions ?? 0,
    nodes_with_custom_prompts: prompts.length,
  };
}

// ── CSAT ──────────────────────────────────────────────────────────────────────

/** Customer submits a 1–5 star rating after session ends. */
export async function submitCsatRating(
  sessionId: string,
  rating: number,
): Promise<void> {
  const res = await fetch(`/api/workspace/sessions/${sessionId}/csat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ rating }),
  });
  if (!res.ok) throw new Error(`CSAT submission failed: ${res.status}`);
}


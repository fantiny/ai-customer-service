export type MessageRole = 'user' | 'bot' | 'agent' | 'system' | 'note';

export type TicketStatus = 'open' | 'in_progress' | 'pending_reply' | 'resolved' | 'closed';

export interface Ticket {
  ticket_id: string;
  session_id: string;
  user_id: string;
  status: TicketStatus;
  category: string | null;
  assigned_agent_id: string | null;
  resolution: string | null;
  summary: string | null;
  created_at: string;
  resolved_at: string | null;
}

// Source citation from unified_agent_node tool calls (workspace-only, not shown to customers)
export interface SourceRef {
  type: 'knowledge' | 'order' | 'product';
  id: string;
  title: string;
  knowledge_type?: 'business_policy' | 'industry_knowledge';
}

export interface ChatMsg {
  role: MessageRole;
  content: string;
  timestamp: string;
  agent_id?: string;
  sources?: SourceRef[];  // only present on workspace new_message events (not on bot_reply to customer)
}

export type SessionMode = 'ai' | 'hitl_pending' | 'human';

export interface PendingAction {
  action: string;             // cancel_order | initiate_refund | request_rush | exchange_order
  action_label: string;       // 取消婚纱订单 | 申请退款 | 申请加急制作
  order_id: string;
  user_id: string;
  rush_level?: string;
  ai_analysis?: string;       // Rule-based one-line hint for HITL agent (e.g. "婚纱已进入裁剪阶段，预计退款约50%")
}

export interface OrderContext {
  order_id: string;
  status: string;
  total: number;
  dress_style?: string;
  color?: string;
  is_custom: boolean;
  is_rush: boolean;
  production_stage?: string;
  wedding_date?: string;
  estimated_completion?: string;
  rush_level?: string;
  items: { name: string; quantity: number; unit_price: number }[];
}

export interface SessionInfo {
  session_id: string;
  user_id: string;
  thread_id: string;
  mode: SessionMode;
  history: ChatMsg[];
  pending_action: PendingAction | null;
  order_context: OrderContext | null;
  escalation_reason: string | null;  // internal only — shown to agents, never to customers
  assigned_agent_id: string | null;  // set after claim_session
  is_urgent?: boolean;               // wedding date within urgent threshold
  last_intent?: string;              // most recent classified intent for session card chip
}

export interface AgentInfo {
  agent_id: string;
  name: string;
  status: 'online' | 'offline' | 'busy';
}

// ── Admin panel types ──────────────────────────────────────────────────────

export interface KnowledgeDoc {
  doc_id: string;
  title: string;
  content?: string;
  preview?: string;
  category: string;
  knowledge_type: 'business_policy' | 'industry_knowledge';
  has_embedding: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface BusinessRule {
  rule_key: string;
  rule_value: string;
  description: string;
  updated_at?: string;
}

export interface NodePrompt {
  node_name: string;
  version: number;
  content: string;
  active: boolean;
  created_at?: string;
}

export interface PromptHistory {
  node_name: string;
  active_version: number;
  active_content: string;
  history: Array<{ prompt_id: string; version: number; content: string; created_at: string }>;
}

export interface TodayMetrics {
  date: string;
  total_sessions: number;
  ai_resolved: number;
  escalated_to_human: number;
  resolved: number;
  avg_resolve_min: number | null;
  hitl_approvals: number;
  hitl_rejections: number;
  avg_first_response_ms: number;
}

export interface AnalyticsData {
  period_days: number;
  tickets: number;           // total session/ticket count
  total_sessions: number;   // alias for tickets
  ai_resolved: number;
  resolved_count: number;
  open_count: number;
  escalated_to_human: number;
  hitl_count: number;
  avg_resolution_minutes: number | null;
  avg_bot_response_ms: number;
  resolution_rate: number;
  categories: Record<string, number>;
  resolution_types: Record<string, number>;
  sentiment_at_start: Record<string, number>;
  ai_quality: Record<string, number>;
  csat: { avg_rating: number | null; count: number };
  daily_volume: Array<{ date: string; count: number }>;
  intent_distribution: Record<string, number>;
  top_intents: Array<{ intent: string; count: number }>;
  category_distribution: Array<{ category: string; count: number }>;
  escalation_by_node: Array<{ node: string; count: number }>;
}

export interface Digest {
  digest_id: string;
  report_date: string;
  metrics: Record<string, unknown>;
  summary_md: string;
  created_at: string;
}

export interface SystemHealth {
  total_documents: number;
  with_embedding: number;
  embedding_coverage: number;
  business_policy_count: number;
  industry_knowledge_count: number;
  business_rules_count: number;
  products_count: number;
  active_sessions: number;
  nodes_with_custom_prompts: number;
}

export interface AdminChatMessage {
  role: 'human' | 'ai' | 'tool';
  content: string;
  tool_name?: string;
  timestamp?: string;
}

export interface ProductInfo {
  product_id: string;
  name: string;
  style: string;
  price: number;
  deposit_rate: number;
  production_days: number;
  rush_available: boolean;
  stock_type: 'ready' | 'custom';
  colors: string[];
  tags: string[];
  description: string;
  occasions: string[];
  active: boolean;
  purchase_url: string;
}

export type AdminSection = 'overview' | 'knowledge' | 'rules' | 'prompts' | 'digest' | 'products';

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  Cpu, Users, ShieldAlert, Send, CheckCircle2, XCircle,
  Sparkles, Clock, Crown, Zap, Heart, MessageCircle, TicketCheck,
  History, BarChart3, X, ChevronRight, AlertCircle, ThumbsUp, ThumbsDown, Minus,
  Loader2, Search, Frown, AlertTriangle, UserCheck, Package, BookOpen, StickyNote,
} from 'lucide-react';
import socket from '../lib/socket';
import { SessionInfo, ChatMsg, PendingAction, AgentInfo, SourceRef } from '../types';
import { agentKnowledgeSearch, addSessionNote, getKnowledgeDoc, type KBSearchResult } from '../lib/adminApi';

// ─── helpers ─────────────────────────────────────────────────────────────────

const MODE_BADGE: Record<string, { label: string; color: string }> = {
  hitl_pending: { label: 'HITL',  color: '#F59E0B' },
  human:        { label: 'AGENT', color: '#10B981' },
  ai:           { label: 'AI',    color: '#3B82F6' },
};

const ACTION_ICON: Record<string, React.ReactNode> = {
  cancel_order:    <XCircle size={14} />,
  initiate_refund: <Heart size={14} />,
  request_rush:    <Zap size={14} />,
};

// ─── Canned responses ─────────────────────────────────────────────────────────

const CANNED_REPLIES: { label: string; text: string }[] = [
  { label: '感谢等待',    text: '感谢您的耐心等待，我这边马上为您处理 💕' },
  { label: '订单查询中', text: '好的，我正在查询您的订单信息，请稍等一下～' },
  { label: '退货政策',   text: '我们支持收货7天内退货（定制款以制作阶段计算退款比例），请告诉我您的订单号，我来帮您确认具体情况。' },
  { label: '换货流程',   text: '换货需要在收货7天内申请，请提供订单号和具体问题描述（尺寸/做工/款式），我为您提交换货工单。' },
  { label: '转专属顾问', text: '您的问题需要专属顾问为您跟进，我会立即帮您安排，稍后顾问会主动联系您，请保持手机畅通 📞' },
  { label: '加急说明',   text: '加急分两档：标准加急30天交货（+50%附加费），特急15天交货（+100%附加费），需提前确认产能。请告诉我您的婚礼日期，我帮您评估。' },
  { label: '感谢信任',   text: '感谢您对缘梦婚纱的信任与支持，祝您婚礼顺利幸福！如有任何需要随时联系我们 💕' },
  { label: '稍候处理',   text: '您好，我需要核实一下相关信息，请给我2-3分钟，马上回复您～' },
];

const API_BASE = 'http://localhost:8000';

/** Parse message content into text/image segments. */
function parseContent(content: string): Array<{ type: 'text' | 'image'; value: string }> {
  const parts: Array<{ type: 'text' | 'image'; value: string }> = [];
  const regex = /\[IMAGE:(https?:\/\/[^\]]+|\/uploads\/[^\]]+)\]/g;
  let last = 0, m;
  while ((m = regex.exec(content)) !== null) {
    if (m.index > last) parts.push({ type: 'text', value: content.slice(last, m.index) });
    parts.push({ type: 'image', value: m[1] });
    last = m.index + m[0].length;
  }
  if (last < content.length) parts.push({ type: 'text', value: content.slice(last) });
  return parts.length > 0 ? parts : [{ type: 'text', value: content }];
}

function MsgContent({ content, textStyle }: { content: string; textStyle?: React.CSSProperties }) {
  const parts = parseContent(content);
  return (
    <>
      {parts.map((p, i) =>
        p.type === 'image' ? (
          <img key={i} src={p.value.startsWith('/') ? `${API_BASE}${p.value}` : p.value}
               alt="图片附件"
               style={{ maxWidth: '100%', maxHeight: 220, borderRadius: 10, marginTop: 4, display: 'block',
                        objectFit: 'contain', border: '1px solid rgba(255,255,255,0.08)' }} />
        ) : (
          <span key={i} style={{ whiteSpace: 'pre-wrap', ...textStyle }}>{p.value}</span>
        )
      )}
    </>
  );
}

function daysUntil(dateStr?: string | null): number | null {
  if (!dateStr) return null;
  const diff = new Date(dateStr).getTime() - Date.now();
  return Math.ceil(diff / 86_400_000);
}

function stageLabel(stage?: string): string {
  const map: Record<string, string> = {
    pending: '待排产', confirmed: '已排产', cutting: '面料剪裁',
    sewing: '主体缝制', beading: '珠绣工艺', qc: '质量检验', ready: '制作完成',
  };
  return map[stage ?? ''] ?? stage ?? '—';
}

// ─── context panel ────────────────────────────────────────────────────────────

function ContextPanel({ session, onApprove, onReject, onTransferToAgent, onTransferToBot }: {
  session: SessionInfo | null;
  onApprove: () => void;
  onReject: () => void;
  onTransferToAgent: (note: string) => void;
  onTransferToBot: () => void;
}) {
  const [rejectNote, setRejectNote] = useState('');
  const [showReject, setShowReject] = useState(false);
  // Prevent double-click on HITL buttons; resets automatically when session changes
  const [hitlProcessing, setHitlProcessing] = useState(false);
  // Prevent duplicate clicks on transfer buttons; resets automatically when session changes
  const [transferProcessing, setTransferProcessing] = useState(false);
  // I9: Transfer handoff notes
  const [showTransferInput, setShowTransferInput] = useState(false);
  const [transferNote, setTransferNote] = useState('');
  const sessionId = session?.session_id;
  useEffect(() => { setHitlProcessing(false); }, [sessionId]);
  useEffect(() => { setTransferProcessing(false); setShowTransferInput(false); setTransferNote(''); }, [sessionId]);

  // I5: Keyboard shortcuts for HITL (Enter = approve, Esc = reject)
  useEffect(() => {
    if (session?.mode !== 'hitl_pending' || hitlProcessing) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
        e.preventDefault();
        setHitlProcessing(true);
        onApprove();
      } else if (e.key === 'Escape') {
        e.preventDefault();
        setHitlProcessing(true);
        onReject();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [session?.mode, hitlProcessing, onApprove, onReject]);

  if (!session) {
    return (
      <aside className="flex flex-col items-center justify-center h-full opacity-10 gap-3">
        <Crown size={32} />
        <span className="text-xs uppercase tracking-widest">选择会话</span>
      </aside>
    );
  }

  const { order_context: oc, pending_action: pa, mode, escalation_reason } = session;
  const days = daysUntil(oc?.wedding_date);
  const isUrgent = days !== null && days < 30;

  return (
    <aside className="flex flex-col overflow-y-auto h-full">
      {/* ── Internal escalation notice (agents only, never shown to customers) ── */}
      {escalation_reason && (
        <div className="mx-3 mt-3 rounded-lg px-3 py-2 text-xs border"
             style={{ background: 'rgba(239,68,68,0.08)', borderColor: 'rgba(239,68,68,0.3)', color: 'var(--color-rose)' }}>
          <div className="font-semibold mb-0.5">⚠ 内部备注（客户不可见）</div>
          <div style={{ color: 'var(--color-muted)', wordBreak: 'break-all' }}>{escalation_reason}</div>
        </div>
      )}

      {/* ── Customer card ── */}
      <Section title="客户信息">
        <div className="rounded-lg p-3 border text-xs space-y-2"
             style={{ background: 'var(--color-surface-2)', borderColor: isUrgent ? 'var(--color-rose)' : 'var(--color-border)' }}>
          <div className="flex justify-between">
            <span style={{ color: 'var(--color-muted)' }}>用户 ID</span>
            <span className="font-mono">{session.user_id}</span>
          </div>
          <div className="flex justify-between">
            <span style={{ color: 'var(--color-muted)' }}>会话状态</span>
            <ModeChip mode={mode} />
          </div>
          {days !== null && (
            <div className="flex justify-between items-center">
              <span style={{ color: 'var(--color-muted)' }}>婚礼倒计时</span>
              <span className="font-bold" style={{ color: isUrgent ? 'var(--color-rose)' : 'var(--color-green)' }}>
                {isUrgent && '⚠️ '}距今 {days} 天
              </span>
            </div>
          )}
        </div>
      </Section>

      {/* ── Order details ── */}
      {oc && (
        <Section title="婚纱订单">
          <div className="rounded-lg p-3 border text-xs space-y-2"
               style={{ background: 'var(--color-surface-2)', borderColor: 'var(--color-border)' }}>
            <Row label="订单号" value={oc.order_id} mono />
            <Row label="商品" value={oc.items?.[0]?.name ?? '—'} />
            <Row label="金额" value={oc.total != null ? `¥${oc.total.toLocaleString()}` : '—'} />
            {oc.is_custom && <Row label="生产阶段" value={stageLabel(oc.production_stage)} />}
            {oc.estimated_completion && <Row label="预计完成" value={oc.estimated_completion} />}
            {oc.is_rush && (
              <div className="flex justify-between items-center">
                <span style={{ color: 'var(--color-muted)' }}>加急等级</span>
                <span className="text-[10px] px-2 py-0.5 rounded font-bold"
                      style={{ background: 'rgba(245,158,11,0.15)', color: 'var(--color-amber)' }}>
                  {oc.rush_level === 'super_rush' ? '特急' : '加急'}
                </span>
              </div>
            )}
          </div>
        </Section>
      )}

      {/* ── HITL approval card ── */}
      {mode === 'hitl_pending' && pa && (
        <Section title="HITL 待审批">
          <div className="rounded-lg p-4 border space-y-3"
               style={{ background: 'rgba(245,158,11,0.06)', borderColor: 'rgba(245,158,11,0.3)' }}>
            <div className="flex items-center gap-2 text-xs font-bold" style={{ color: 'var(--color-amber)' }}>
              {ACTION_ICON[pa.action] ?? <ShieldAlert size={14} />}
              {pa.action_label}
            </div>
            <div className="text-[11px] space-y-1.5" style={{ color: 'var(--color-muted)' }}>
              <div>订单：<span style={{ color: 'var(--color-text)' }} className="font-mono">{pa.order_id}</span></div>
              {pa.rush_level && (
                <div>加急等级：<span style={{ color: 'var(--color-text)' }}>
                  {pa.rush_level === 'super_rush' ? '特急（+100%）' : '加急（+50%）'}
                </span></div>
              )}
            </div>
            {/* F3: AI pre-analysis hint — rule-based, zero latency */}
            {pa.ai_analysis && (
              <div className="text-[11px] italic px-2 py-1.5 rounded"
                   style={{ background: 'rgba(245,158,11,0.08)', color: 'var(--color-muted)', borderLeft: '2px solid var(--color-amber)' }}>
                AI 分析：{pa.ai_analysis}
              </div>
            )}

            {!showReject ? (
              <div className="space-y-2 pt-1">
                <div className="flex gap-2">
                  {/* 批准 — solid green, primary action */}
                  <button
                    disabled={hitlProcessing}
                    onClick={() => { if (!hitlProcessing) { setHitlProcessing(true); onApprove(); } }}
                    className="flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg text-[11px] font-bold transition-all active:scale-[0.97] hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
                    style={{ background: 'var(--color-green)', color: '#0B1220', boxShadow: hitlProcessing ? 'none' : '0 2px 8px rgba(16,185,129,0.4)' }}>
                    <CheckCircle2 size={12} /> {hitlProcessing ? '处理中…' : '批准'}
                  </button>
                  {/* 拒绝 — rose background (not transparent), secondary destructive */}
                  <button
                    disabled={hitlProcessing}
                    onClick={() => { if (!hitlProcessing) setShowReject(true); }}
                    className="flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg text-[11px] font-bold transition-all active:scale-[0.97] hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
                    style={{ border: '1px solid rgba(239,68,68,0.5)', color: 'var(--color-rose)', background: 'rgba(239,68,68,0.12)' }}>
                    <XCircle size={12} /> 拒绝
                  </button>
                </div>
                {/* keyboard shortcut hint — clearly a hint (small, centered, muted) */}
                <p className="text-[9px] text-center italic" style={{ color: 'var(--color-muted)', opacity: 0.6 }}>⌨ Enter 批准 · Esc 拒绝</p>
              </div>
            ) : (
              <div className="space-y-2">
                <textarea
                  value={rejectNote}
                  onChange={e => setRejectNote(e.target.value)}
                  placeholder="拒绝原因（可选）"
                  rows={2}
                  className="w-full rounded-lg px-2 py-1.5 text-[11px] resize-none border outline-none"
                  style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)', color: 'var(--color-text)' }}
                />
                <div className="flex gap-2">
                  <button
                    disabled={hitlProcessing}
                    onClick={() => { if (!hitlProcessing) { setHitlProcessing(true); onReject(); setShowReject(false); setRejectNote(''); } }}
                    className="flex-1 py-2 rounded-lg text-[11px] font-bold transition-all active:scale-[0.97] hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed"
                    style={{ background: 'var(--color-rose)', color: '#fff', boxShadow: hitlProcessing ? 'none' : '0 2px 8px rgba(239,68,68,0.35)' }}>
                    {hitlProcessing ? '处理中…' : '确认拒绝'}
                  </button>
                  <button onClick={() => setShowReject(false)}
                    className="flex-1 py-2 rounded-lg text-[11px] font-bold transition-all hover:opacity-80 active:scale-[0.97]"
                    style={{ border: '1px solid var(--color-border)', color: 'var(--color-muted)', background: 'var(--color-surface-2)' }}>
                    取消
                  </button>
                </div>
              </div>
            )}
          </div>
        </Section>
      )}

      {/* ── AI Co-pilot suggestions ── */}
      <Section title="AI 协同建议">
        <CoPilotSuggestions session={session} />
      </Section>

      {/* ── Quick actions ── */}
      <Section title="会话操作">
        <div className="flex flex-col gap-2">
          {mode !== 'human' && !showTransferInput && (
            <ActionBtn icon={<Users size={12} />}
              onClick={() => setShowTransferInput(true)}
              disabled={transferProcessing}
              color="var(--color-blue)"
              label={transferProcessing ? '处理中…' : '转接人工'} />
          )}
          {/* I9: Transfer handoff note input */}
          {mode !== 'human' && showTransferInput && (
            <div className="space-y-2">
              <textarea
                value={transferNote}
                onChange={e => setTransferNote(e.target.value)}
                placeholder="交接备注（可选）：例如客户已确认退款金额"
                rows={2}
                className="w-full rounded px-2 py-1.5 text-[11px] resize-none border outline-none"
                style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)', color: 'var(--color-text)' }}
              />
              <div className="flex gap-2">
                <button
                  disabled={transferProcessing}
                  onClick={() => { if (!transferProcessing) { onTransferToAgent(transferNote); setTransferProcessing(true); setShowTransferInput(false); setTransferNote(''); } }}
                  className="flex-1 py-2 rounded-lg text-[11px] font-bold transition-all active:scale-[0.97] hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed"
                  style={{ background: 'var(--color-blue)', color: '#fff', boxShadow: transferProcessing ? 'none' : '0 2px 8px rgba(59,130,246,0.35)' }}>
                  确认转接
                </button>
                <button
                  onClick={() => { setShowTransferInput(false); setTransferNote(''); }}
                  className="flex-1 py-2 rounded-lg text-[11px] font-bold transition-all hover:opacity-80 active:scale-[0.97]"
                  style={{ border: '1px solid var(--color-border)', color: 'var(--color-muted)', background: 'var(--color-surface-2)' }}>
                  取消
                </button>
              </div>
            </div>
          )}
          {(mode === 'human' || mode === 'hitl_pending') && (
            <ActionBtn icon={<Cpu size={12} />}
              onClick={() => { setTransferProcessing(true); onTransferToBot(); }}
              disabled={transferProcessing}
              color="var(--color-muted)"
              label={transferProcessing ? '处理中…' : '回交 AI'} />
          )}
        </div>
      </Section>
    </aside>
  );
}

function CoPilotSuggestions({ session }: { session: SessionInfo }) {
  const { mode, pending_action: pa, order_context: oc, history, escalation_reason } = session;

  const suggestions: string[] = [];

  // ── HITL: approval guidance ──────────────────────────────────────────────
  if (mode === 'hitl_pending' && pa) {
    if (pa.action === 'cancel_order') {
      const stage = oc?.production_stage;
      if (stage === 'cutting') suggestions.push('婚纱处于剪裁阶段，退款比例为50%，可向客户说明损耗原因。');
      else if (stage === 'sewing' || stage === 'beading') suggestions.push('婚纱主体已成型，按协议无法退款，建议转人工协商。');
      else suggestions.push('订单满足取消条件，可直接批准。');
    }
    if (pa.action === 'request_rush') suggestions.push('确认产能后批准，附加费将单独通知客户付款。');
    if (pa.action === 'initiate_refund') suggestions.push('已送达订单可直接批准退款，3-5个工作日到账。');
  }

  // ── Human mode: context-aware guidance ──────────────────────────────────
  if (mode === 'human') {
    suggestions.push('您正在人工接管模式，回复后将直达客户。');

    // Escalation reason hint
    if (escalation_reason && !escalation_reason.includes('AI 服务')) {
      suggestions.push(`接管原因：${escalation_reason}`);
    }

    // Wedding urgency
    if (oc?.wedding_date) {
      const d = daysUntil(oc.wedding_date);
      if (d !== null && d < 20) suggestions.push(`⚠️ 客户婚礼仅剩 ${d} 天，请优先处理，可申请加急通道。`);
    }

    // Order context hints
    if (oc?.status) {
      const stageMap: Record<string, string> = {
        preparing: '备料中', cutting: '裁剪中', sewing: '缝制中',
        embroidering: '刺绣中', finishing: '后处理中', quality_check: '质检中',
        packaging: '包装中', shipped: '已发货', in_transit: '运输中', delivered: '已送达',
      };
      const statusLabel = stageMap[oc.production_stage ?? ''] ?? oc.status;
      suggestions.push(`当前订单状态：${statusLabel}（${oc.order_id ?? ''}）`);
    }

    // History analysis: detect if customer repeated same complaint
    if (history && history.length >= 4) {
      const recentUser = history.filter(m => m.role === 'user').slice(-3);
      const hasRepeat = recentUser.length >= 2 &&
        recentUser[recentUser.length - 1].content === recentUser[recentUser.length - 2].content;
      if (hasRepeat) suggestions.push('客户重复发送相同消息，请尽快给出明确答复。');

      // Detect if no order ID provided yet
      const mentionsOrderId = history.some(m =>
        m.role === 'user' && /[A-Z0-9]{6,}/i.test(m.content)
      );
      if (!oc?.order_id && !mentionsOrderId) {
        suggestions.push('客户尚未提供订单号，可直接询问以便查单。');
      }
    }
  }

  // ── AI mode: monitoring hints ────────────────────────────────────────────
  if (mode === 'ai') {
    if (oc?.wedding_date) {
      const d = daysUntil(oc.wedding_date);
      if (d !== null && d < 14) suggestions.push(`⚠️ 客户婚礼仅剩 ${d} 天（紧急），AI 已标记优先处理。`);
    }
  }

  if (!suggestions.length) suggestions.push('当前无特别建议，AI 正在处理中。');

  return (
    <div className="space-y-2">
      {suggestions.map((s, i) => (
        <div key={i} className="rounded-lg p-3 border-l-2 text-[11px] leading-relaxed"
             style={{ background: 'var(--color-surface-2)', borderColor: 'var(--color-green)', color: 'var(--color-text)' }}>
          <div className="flex items-center gap-1 mb-1 font-bold text-[10px]" style={{ color: 'var(--color-green)' }}>
            <Sparkles size={10} /> AI 建议
          </div>
          {s}
        </div>
      ))}
    </div>
  );
}

// ─── agent login screen ───────────────────────────────────────────────────────

function AgentLoginScreen({ onLogin }: { onLogin: (id: string, name: string) => void }) {
  const [agentId, setAgentId] = useState('');
  const [name, setName]       = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const id = agentId.trim() || `agent-${Math.random().toString(36).slice(2, 7)}`;
    const n  = name.trim() || id;
    onLogin(id, n);
  };

  return (
    <div className="flex h-screen items-center justify-center"
         style={{ background: 'var(--color-bg)', color: 'var(--color-text)' }}>
      <motion.form
        onSubmit={handleSubmit}
        initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}
        className="w-[340px] rounded-2xl border p-8 space-y-5 shadow-2xl"
        style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
        <div className="flex items-center gap-2 mb-2">
          <div className="w-8 h-8 rounded-lg flex items-center justify-center font-bold text-base shadow"
               style={{ background: 'var(--color-pink)', boxShadow: '0 0 12px var(--color-pink-glow)' }}>💐</div>
          <span className="font-semibold text-base">客服工作台登录</span>
        </div>
        <div className="space-y-3">
          <div>
            <label className="text-[11px] uppercase tracking-widest font-bold block mb-1"
                   style={{ color: 'var(--color-muted)' }}>
              顾问工号（可选）
            </label>
            <input
              value={agentId}
              onChange={e => setAgentId(e.target.value)}
              placeholder="留空自动生成"
              className="w-full rounded-lg px-3 py-2 text-sm border outline-none"
              style={{ background: 'var(--color-surface-2)', borderColor: 'var(--color-border)', color: 'var(--color-text)' }}
            />
          </div>
          <div>
            <label className="text-[11px] uppercase tracking-widest font-bold block mb-1"
                   style={{ color: 'var(--color-muted)' }}>
              顾问姓名
            </label>
            <input
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="例：李婉清"
              className="w-full rounded-lg px-3 py-2 text-sm border outline-none"
              style={{ background: 'var(--color-surface-2)', borderColor: 'var(--color-border)', color: 'var(--color-text)' }}
            />
          </div>
        </div>
        <button type="submit"
          className="w-full py-2.5 rounded-lg text-sm font-bold transition-all"
          style={{ background: 'var(--color-blue)', color: '#fff' }}>
          进入工作台
        </button>
      </motion.form>
    </div>
  );
}

// ─── resolve dialog ───────────────────────────────────────────────────────────

function ResolveDialog({ sessionId, onClose, onResolved }: {
  sessionId: string;
  onClose: () => void;
  onResolved: () => void;
}) {
  const [resolution, setResolution] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = () => {
    setLoading(true);
    setError('');
    socket.emit(
      'resolve_session',
      { session_id: sessionId, resolution: resolution.trim() || undefined },
      (resp: { success: boolean; message: string }) => {
        setLoading(false);
        if (resp?.success) {
          onResolved();
          onClose();
        } else {
          setError(resp?.message ?? '结单失败，请重试');
        }
      }
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center"
         style={{ background: 'rgba(0,0,0,0.6)' }}
         onClick={e => e.target === e.currentTarget && onClose()}>
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        exit={{ opacity: 0, scale: 0.95 }}
        className="w-[380px] rounded-xl border p-6 space-y-4 shadow-2xl"
        style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
        <div className="flex items-center gap-2">
          <TicketCheck size={18} style={{ color: 'var(--color-green)' }} />
          <span className="font-semibold">结单确认</span>
        </div>
        <p className="text-[12px]" style={{ color: 'var(--color-muted)' }}>
          工单将标记为已解决，客户问题记录存档。
        </p>
        <div>
          <label className="text-[11px] uppercase tracking-widest font-bold block mb-1.5"
                 style={{ color: 'var(--color-muted)' }}>
            解决说明（必填）
          </label>
          <textarea
            value={resolution}
            onChange={e => setResolution(e.target.value)}
            placeholder="简要描述问题如何解决…"
            rows={3}
            className="w-full rounded-lg px-3 py-2 text-[13px] resize-none border outline-none focus:ring-1"
            style={{
              background: 'var(--color-surface-2)',
              borderColor: 'var(--color-border)',
              color: 'var(--color-text)',
            }}
          />
        </div>
        {error && (
          <p className="text-[11px]" style={{ color: 'var(--color-rose)' }}>{error}</p>
        )}
        <div className="flex gap-2 pt-1">
          <button
            disabled={!resolution.trim() || loading}
            onClick={() => { if (resolution.trim()) { handleSubmit(); } }}
            className="flex-1 flex items-center justify-center gap-2 py-2 rounded-lg text-[12px] font-bold transition-all active:scale-[0.97] hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed"
            style={{ background: 'var(--color-green)', color: '#0B1220', boxShadow: resolution.trim() && !loading ? '0 2px 10px rgba(16,185,129,0.4)' : 'none' }}>
            <CheckCircle2 size={13} />
            {loading ? '处理中…' : resolution.trim() ? '确认结单' : '请填写处理结果'}
          </button>
          <button
            onClick={onClose}
            className="flex-1 py-2 rounded-lg text-[12px] font-bold transition-all hover:opacity-80 active:scale-[0.97]"
            style={{ border: '1px solid var(--color-border)', color: 'var(--color-muted)', background: 'var(--color-surface-2)' }}>
            取消
          </button>
        </div>
      </motion.div>
    </div>
  );
}

// ─── session list helpers ─────────────────────────────────────────────────────

function secondsAgo(isoStr: string | undefined): number {
  if (!isoStr) return 0;
  return Math.floor((Date.now() - new Date(isoStr).getTime()) / 1000);
}

/** Format elapsed seconds into a compact wait-time string */
function formatWait(isoStr: string | undefined): string {
  if (!isoStr) return '';
  const s = secondsAgo(isoStr);
  if (s < 60) return '刚刚';
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  return `${Math.floor(m / 60)}h${m % 60 > 0 ? `${m % 60}m` : ''}`;
}

const NEG_WORDS = ['投诉', '退款', '不满', '生气', '愤怒', '差劲', '骗', '烂', '太差', '不行', '退货', '索赔', '赔偿', '崩溃', '绝望', '骗子', '差评'];

/** Heuristically detect negative sentiment from last few user messages */
function detectNegative(history: ChatMsg[]): boolean {
  const recent = history.filter(m => m.role === 'user').slice(-3);
  return recent.some(m => NEG_WORDS.some(w => m.content.includes(w)));
}

/** Compute all status flags for a session */
function computeFlags(sess: SessionInfo, slaWarning?: string) {
  const days = daysUntil(sess.order_context?.wedding_date);
  const urgent = days !== null && days < 14;
  const negative = detectNegative(sess.history);
  const lastUserMsg = [...sess.history].reverse().find(m => m.role === 'user');
  const waitSec = secondsAgo(lastUserMsg?.timestamp);
  const longWait = waitSec > 300; // > 5 min
  const humanRecommended = sess.mode === 'ai' && (negative || urgent || longWait);
  return { days, urgent, negative, longWait, humanRecommended, hasSla: !!slaWarning, lastUserMsg };
}

/** F4: Intent label chip — maps intent id → display label and color */
const INTENT_LABEL: Record<string, { label: string; color: string; bg: string }> = {
  order_read:         { label: '查询订单',   color: '#10B981', bg: 'rgba(16,185,129,0.12)' },
  order_write:        { label: '订单操作',   color: '#F59E0B', bg: 'rgba(245,158,11,0.12)' },
  faq:                { label: '政策咨询',   color: '#06B6D4', bg: 'rgba(6,182,212,0.12)' },
  aftersales:         { label: '售后投诉',   color: '#F97316', bg: 'rgba(249,115,22,0.12)' },
  product:            { label: '商品推荐',   color: '#3B82F6', bg: 'rgba(59,130,246,0.12)' },
  measurement_guide:  { label: '量体引导',   color: '#8B5CF6', bg: 'rgba(139,92,246,0.12)' },
};

function IntentChip({ intent }: { intent?: string }) {
  if (!intent) return null;
  const meta = INTENT_LABEL[intent];
  if (!meta) return null;
  return (
    <span className="text-[8px] px-1.5 py-0.5 rounded font-bold shrink-0"
          style={{ color: meta.color, background: meta.bg }}>
      {meta.label}
    </span>
  );
}

/** Tiny action chip — replaces large full-width action buttons */
function ActionChip({ label, loading, color, onClick }: {
  label: string; loading: boolean;
  color: 'blue' | 'amber';
  onClick: (e: React.MouseEvent) => void;
}) {
  const C = color === 'blue'
    ? { bg: 'rgba(59,130,246,0.18)', hbg: 'rgba(59,130,246,0.32)', border: 'rgba(59,130,246,0.45)', text: 'var(--color-blue)' }
    : { bg: 'rgba(245,158,11,0.18)', hbg: 'rgba(245,158,11,0.32)', border: 'rgba(245,158,11,0.45)', text: 'var(--color-amber)' };
  const [hov, setHov] = useState(false);
  return (
    <button
      disabled={loading}
      onClick={onClick}
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
      title={label}
      className="shrink-0 flex items-center gap-0.5 px-1.5 py-0.5 rounded font-bold text-[9px] transition-all active:scale-[0.95] disabled:opacity-40"
      style={{ background: hov ? C.hbg : C.bg, border: `1px solid ${C.border}`, color: C.text }}>
      {loading ? <Loader2 size={8} className="animate-spin" /> : label}
    </button>
  );
}

function SessionList({ sessions, allSessions, activeId, myAgentId, slaWarnings, unreadCounts, customerTyping, onSelect, onClaim, onIntervene }: {
  sessions: SessionInfo[];
  allSessions: SessionInfo[];
  activeId: string | null;
  myAgentId: string;
  slaWarnings: Record<string, string>;
  unreadCounts: Record<string, number>;
  customerTyping: Record<string, boolean>;
  onSelect: (s: SessionInfo) => void;
  onClaim: (sessionId: string) => Promise<{ ok: boolean; message?: string }>;
  onIntervene: (sessionId: string) => Promise<{ ok: boolean; message?: string }>;
}) {
  // I7: Ticker to keep countdown timers fresh every 10 seconds
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick(t => t + 1), 10000);
    return () => clearInterval(id);
  }, []);

  // Track which session's button is currently loading
  const [actingId, setActingId] = useState<string | null>(null);
  // Inline toast: { id, ok, text }
  const [toast, setToast] = useState<{ id: string; ok: boolean; text: string } | null>(null);

  const showToast = (id: string, ok: boolean, text: string) => {
    setToast({ id, ok, text });
    setTimeout(() => setToast(null), 3000);
  };

  const doClaim = async (e: React.MouseEvent, sessId: string) => {
    e.stopPropagation();
    setActingId(sessId);
    const result = await onClaim(sessId);
    setActingId(null);
    if (result.ok) showToast(sessId, true, '✓ 已认领，对话已打开');
    else showToast(sessId, false, result.message ?? '认领失败，请重试');
  };

  const doIntervene = async (e: React.MouseEvent, sessId: string) => {
    e.stopPropagation();
    setActingId(sessId);
    const result = await onIntervene(sessId);
    setActingId(null);
    if (result.ok) showToast(sessId, true, '✓ 已接管，可开始回复客户');
    else showToast(sessId, false, result.message ?? '接管失败，请重试');
  };

  // AI-mode sessions not already in the pending queue
  const queueIds = new Set(sessions.map(s => s.session_id));
  const aiSessions = allSessions.filter(s => s.mode === 'ai' && !queueIds.has(s.session_id));

  // Search filter
  const [search, setSearch] = useState('');
  const q = search.trim().toLowerCase();
  const filteredQueue = q ? sessions.filter(s => s.user_id.toLowerCase().includes(q) || s.session_id.toLowerCase().includes(q)) : sessions;
  const filteredAi = q ? aiSessions.filter(s => s.user_id.toLowerCase().includes(q) || s.session_id.toLowerCase().includes(q)) : aiSessions;

  /** Compact inline toast */
  const InlineToast = ({ id }: { id: string }) =>
    toast?.id === id ? (
      <div className="mt-1.5 px-2 py-1 rounded text-[10px] font-semibold"
           style={{
             background: toast.ok ? 'rgba(16,185,129,0.15)' : 'rgba(239,68,68,0.15)',
             color: toast.ok ? 'var(--color-green)' : 'var(--color-rose)',
             border: `1px solid ${toast.ok ? 'rgba(16,185,129,0.3)' : 'rgba(239,68,68,0.3)'}`,
           }}>
        {toast.text}
      </div>
    ) : null;

  return (
    <aside className="flex flex-col border-r overflow-hidden h-full" style={{ borderColor: 'var(--color-border)' }}>

      {/* ── Search ── */}
      <div className="px-3 py-2 border-b shrink-0" style={{ borderColor: 'var(--color-border)' }}>
        <div className="flex items-center gap-2 rounded-lg px-2.5 py-1.5 border"
             style={{ background: 'var(--color-bg)', borderColor: 'var(--color-border)' }}>
          <Search size={11} style={{ color: 'var(--color-muted)', flexShrink: 0 }} />
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="搜索客户 ID 或会话…"
            className="flex-1 bg-transparent text-[11px] outline-none"
            style={{ color: 'var(--color-text)' }}
          />
          {search && (
            <button onClick={() => setSearch('')} className="shrink-0" style={{ color: 'var(--color-muted)' }}>
              <X size={10} />
            </button>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">

        {/* ── Section 1: pending queue (HITL / human) ── */}
        <div className="px-3 py-1.5 border-b text-[9px] uppercase tracking-widest font-bold flex items-center gap-1.5"
             style={{ borderColor: 'var(--color-border)', color: 'var(--color-muted)', background: 'var(--color-bg)' }}>
          <Users size={9} /> 待处理
          <span className="ml-auto font-mono">{sessions.length}</span>
        </div>

        <AnimatePresence>
          {filteredQueue.map(sess => {
            const badge = MODE_BADGE[sess.mode];
            const isMine = sess.assigned_agent_id === myAgentId;
            const claimedByOther = !!(sess.assigned_agent_id && !isMine);
            const flags = computeFlags(sess, slaWarnings[sess.session_id]);
            const lastVisible = sess.history.filter(m => m.role !== 'system').slice(-1)[0];
            const unread = unreadCounts[sess.session_id] ?? 0;
            const isTyping = customerTyping[sess.session_id];
            const waitStr = formatWait(flags.lastUserMsg?.timestamp);

            return (
              <motion.div key={sess.session_id}
                initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -8 }}
                whileHover={{ backgroundColor: activeId !== sess.session_id ? 'rgba(255,255,255,0.025)' : undefined }}
                whileTap={{ scale: 0.99 }}
                onClick={() => onSelect(sess)}
                className="px-3 py-2.5 border-b cursor-pointer"
                style={{
                  borderColor: 'var(--color-border)',
                  background: activeId === sess.session_id ? 'var(--color-surface-2)' : 'transparent',
                  borderLeft: isMine ? '3px solid var(--color-green)'
                    : activeId === sess.session_id ? '3px solid var(--color-blue)'
                    : '3px solid transparent',
                  opacity: claimedByOther ? 0.55 : 1,
                }}>

                {/* Row 1: user ID + status icons + mode chip + action chip */}
                <div className="flex items-center gap-1 mb-1">
                  <span className="text-[12px] font-semibold truncate flex-1 leading-tight">{sess.user_id}</span>
                  {/* Status icons — small, meaningful */}
                  {flags.negative && <span title="负面情绪" style={{ flexShrink: 0, display: 'flex' }}><Frown size={10} style={{ color: 'var(--color-rose)' }} /></span>}
                  {flags.urgent && <span title={`婚礼仅剩 ${flags.days} 天`} style={{ flexShrink: 0, display: 'flex' }}><AlertTriangle size={10} style={{ color: 'var(--color-amber)' }} /></span>}
                  {flags.hasSla && <span title="响应超时" style={{ flexShrink: 0, display: 'flex' }}><ShieldAlert size={10} style={{ color: 'var(--color-rose)' }} /></span>}
                  {unread > 0 && (
                    <span className="text-[8px] px-1 py-0.5 rounded-full font-bold min-w-[14px] text-center shrink-0"
                          style={{ background: 'var(--color-rose)', color: '#fff' }}>
                      {unread}
                    </span>
                  )}
                  {isMine && (
                    <span className="text-[8px] px-1 py-0.5 rounded font-bold shrink-0"
                          style={{ color: 'var(--color-green)', background: 'rgba(16,185,129,0.15)' }}>我</span>
                  )}
                  {/* F4: Intent chip */}
                  <IntentChip intent={sess.last_intent} />
                  {/* Mode chip */}
                  <span className="text-[8px] px-1.5 py-0.5 rounded font-bold shrink-0"
                        style={{ color: badge.color, background: badge.color + '20' }}>
                    {badge.label}
                  </span>
                  {/* Action chip — small, secondary */}
                  {sess.mode === 'human' && !sess.assigned_agent_id && (
                    <ActionChip label="认领" loading={actingId === sess.session_id} color="blue"
                      onClick={e => doClaim(e, sess.session_id)} />
                  )}
                </div>

                {/* Row 2: last message preview + wait time */}
                <div className="flex items-center gap-2">
                  {isTyping ? (
                    <span className="text-[10px] flex items-center gap-1 flex-1" style={{ color: 'var(--color-blue)' }}>
                      <span className="w-1 h-1 rounded-full animate-bounce" style={{ background: 'var(--color-blue)', animationDelay: '0ms' }} />
                      <span className="w-1 h-1 rounded-full animate-bounce" style={{ background: 'var(--color-blue)', animationDelay: '150ms' }} />
                      <span className="w-1 h-1 rounded-full animate-bounce" style={{ background: 'var(--color-blue)', animationDelay: '300ms' }} />
                      <span className="italic ml-0.5">输入中…</span>
                    </span>
                  ) : (
                    <p className="text-[10px] truncate flex-1 leading-tight" style={{ color: 'var(--color-muted)' }}>
                      {lastVisible ? (
                        <><span style={{ color: lastVisible.role === 'user' ? 'var(--color-text)' : 'var(--color-muted)' }}>
                          {lastVisible.role === 'user' ? '客' : lastVisible.role === 'agent' ? '我' : 'AI'}：
                        </span>{lastVisible.content.replace(/\[IMAGE:[^\]]+\]/g, '[图片]')}</>
                      ) : '会话开始'}
                    </p>
                  )}
                  {waitStr && (
                    <span className="text-[9px] shrink-0 font-mono" style={{ color: flags.longWait ? 'var(--color-rose)' : 'var(--color-muted)', opacity: 0.7 }}>
                      {waitStr}
                    </span>
                  )}
                </div>

                {/* Row 3: conditional context tags (only when meaningful) */}
                {(claimedByOther || sess.mode === 'hitl_pending') && (
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {claimedByOther && (
                      <span className="text-[9px] px-1.5 py-0.5 rounded" style={{ color: 'var(--color-muted)', background: 'var(--color-surface-2)' }}>
                        🔒 {sess.assigned_agent_id}
                      </span>
                    )}
                    {sess.mode === 'hitl_pending' && flags.lastUserMsg && (() => {
                      const secs = secondsAgo(flags.lastUserMsg.timestamp);
                      const m = Math.floor(secs / 60); const s = secs % 60;
                      return (
                        <span className="text-[9px] px-1.5 py-0.5 rounded font-bold" data-tick={tick}
                              style={{ color: 'var(--color-amber)', background: 'rgba(245,158,11,0.15)' }}>
                          ⏳ 待审批 {m}m{s}s
                        </span>
                      );
                    })()}
                  </div>
                )}

                <InlineToast id={sess.session_id} />
              </motion.div>
            );
          })}
        </AnimatePresence>

        {filteredQueue.length === 0 && (
          <div className="px-3 py-6 text-center text-[10px] italic" style={{ color: 'var(--color-muted)', opacity: 0.5 }}>
            {search ? '无匹配会话' : '暂无待处理会话'}
          </div>
        )}

        {/* ── Section 2: AI-mode monitoring sessions ── */}
        {(filteredAi.length > 0 || (!search && aiSessions.length === 0)) && (
          <div className="px-3 py-1.5 border-t border-b text-[9px] uppercase tracking-widest font-bold flex items-center gap-1.5"
               style={{ borderColor: 'var(--color-border)', color: 'var(--color-muted)', background: 'var(--color-bg)' }}>
            <Cpu size={9} /> AI 处理中
            <span className="ml-auto font-mono">{aiSessions.length}</span>
          </div>
        )}

        <AnimatePresence>
          {filteredAi.map(sess => {
            const flags = computeFlags(sess, slaWarnings[sess.session_id]);
            const lastVisible = sess.history.filter(m => m.role !== 'system').slice(-1)[0];
            const waitStr = formatWait(flags.lastUserMsg?.timestamp);
            return (
              <motion.div key={sess.session_id}
                initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -8 }}
                whileHover={{ backgroundColor: activeId !== sess.session_id ? 'rgba(255,255,255,0.025)' : undefined }}
                whileTap={{ scale: 0.99 }}
                onClick={() => onSelect(sess)}
                className="px-3 py-2.5 border-b cursor-pointer"
                style={{
                  borderColor: 'var(--color-border)',
                  background: activeId === sess.session_id ? 'var(--color-surface-2)' : 'transparent',
                  borderLeft: activeId === sess.session_id ? '3px solid var(--color-muted)' : '3px solid transparent',
                }}>

                {/* Row 1: user ID + status icons + mode chip + action chip */}
                <div className="flex items-center gap-1 mb-1">
                  <span className="text-[12px] font-semibold truncate flex-1 leading-tight">{sess.user_id}</span>
                  {flags.negative && <span title="负面情绪" style={{ flexShrink: 0, display: 'flex' }}><Frown size={10} style={{ color: 'var(--color-rose)' }} /></span>}
                  {flags.urgent && <span title={`婚礼仅剩 ${flags.days} 天`} style={{ flexShrink: 0, display: 'flex' }}><AlertTriangle size={10} style={{ color: 'var(--color-amber)' }} /></span>}
                  {flags.humanRecommended && <span title="建议人工介入" style={{ flexShrink: 0, display: 'flex' }}><UserCheck size={10} style={{ color: 'var(--color-purple)' }} /></span>}
                  {/* F4: Intent chip */}
                  <IntentChip intent={sess.last_intent} />
                  <span className="text-[8px] px-1.5 py-0.5 rounded font-bold shrink-0"
                        style={{ color: 'var(--color-muted)', background: 'rgba(112,112,160,0.15)' }}>
                    AI
                  </span>
                  <ActionChip label="接管" loading={actingId === sess.session_id} color="amber"
                    onClick={e => doIntervene(e, sess.session_id)} />
                </div>

                {/* Row 2: last message preview + wait time */}
                <div className="flex items-center gap-2">
                  <p className="text-[10px] truncate flex-1 leading-tight" style={{ color: 'var(--color-muted)' }}>
                    {lastVisible ? (
                      <><span style={{ color: lastVisible.role === 'user' ? 'var(--color-text)' : 'var(--color-muted)' }}>
                        {lastVisible.role === 'user' ? '客' : 'AI'}：
                      </span>{lastVisible.content.replace(/\[IMAGE:[^\]]+\]/g, '[图片]')}</>
                    ) : '会话开始'}
                  </p>
                  {waitStr && (
                    <span className="text-[9px] shrink-0 font-mono" style={{ color: flags.longWait ? 'var(--color-amber)' : 'var(--color-muted)', opacity: 0.7 }}>
                      {waitStr}
                    </span>
                  )}
                </div>

                <InlineToast id={sess.session_id} />
              </motion.div>
            );
          })}
        </AnimatePresence>

        {aiSessions.length === 0 && !search && (
          <div className="px-3 py-5 text-center text-[10px] italic" style={{ color: 'var(--color-muted)', opacity: 0.4 }}>
            暂无 AI 处理中的会话
          </div>
        )}
      </div>
    </aside>
  );
}

// ─── customer chat preview (read-only, no socket) ────────────────────────────

/**
 * Read-only rendering of what the customer sees in their chat window.
 * Uses session.history already loaded by the agent — no new socket connections.
 * Agent identity and customer identity remain completely separate.
 */
function CustomerChatPreview({ session, onClose }: { session: SessionInfo; onClose: () => void }) {
  const bottomRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'instant' });
  }, [session.history.length]);

  const visibleMessages = session.history.filter(m => m.role !== 'system');

  return (
    <div className="absolute inset-0 z-20 flex flex-col"
         style={{ background: 'var(--color-bg)' }}>
      {/* Banner */}
      <div className="flex items-center justify-between px-4 py-2 border-b shrink-0"
           style={{ borderColor: 'var(--color-border)', background: 'rgba(245,158,11,0.06)' }}>
        <span className="text-[11px] font-bold flex items-center gap-1.5" style={{ color: 'var(--color-amber)' }}>
          <MessageCircle size={11} /> 客户视角（只读预览）
        </span>
        <button onClick={onClose}
                className="flex items-center gap-1 text-[10px] px-2 py-1 rounded border font-bold"
                style={{ borderColor: 'var(--color-border)', color: 'var(--color-muted)' }}>
          <X size={10} /> 返回
        </button>
      </div>

      {/* Chat bubbles — customer-style layout */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {visibleMessages.map((msg, i) => {
          const isUser = msg.role === 'user';
          const isAgent = msg.role === 'agent';
          // Customer sees: user messages on right; bot/agent on left
          return (
            <div key={i} className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
              {!isUser && (
                <div className="w-6 h-6 rounded-full flex items-center justify-center text-[10px] shrink-0 mr-2 mt-0.5"
                     style={{ background: isAgent ? 'var(--color-green)' : 'var(--color-pink)', color: '#fff' }}>
                  {isAgent ? '客' : '💐'}
                </div>
              )}
              <div className="max-w-[75%] px-3 py-2 rounded-2xl text-[12px] leading-relaxed whitespace-pre-wrap"
                   style={{
                     background: isUser ? 'var(--color-pink)' : 'var(--color-surface-2)',
                     color: isUser ? '#fff' : 'var(--color-text)',
                     borderRadius: isUser ? '18px 18px 4px 18px' : '18px 18px 18px 4px',
                   }}>
                {msg.content}
              </div>
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>

      {/* Input area — disabled, for visual fidelity only */}
      <div className="px-4 py-3 border-t shrink-0"
           style={{ borderColor: 'var(--color-border)', background: 'var(--color-surface)' }}>
        <div className="flex gap-2 items-center px-3 py-2 rounded-xl border opacity-40 cursor-not-allowed"
             style={{ borderColor: 'var(--color-border)', background: 'var(--color-bg)' }}>
          <span className="flex-1 text-[12px]" style={{ color: 'var(--color-muted)' }}>客户输入框（只读）</span>
          <Send size={14} style={{ color: 'var(--color-muted)' }} />
        </div>
      </div>
    </div>
  );
}

// ─── F6: Source citation chips ────────────────────────────────────────────────

function SourceCitations({ sources }: { sources: SourceRef[] }) {
  const [modalDoc, setModalDoc] = useState<{ title: string; content: string } | null>(null);
  const [loadingId, setLoadingId] = useState<string | null>(null);

  const openKnowledgeDoc = async (src: SourceRef) => {
    if (!src.id) return;
    setLoadingId(src.id);
    try {
      const doc = await getKnowledgeDoc(src.id);
      setModalDoc({ title: doc.title || src.title, content: doc.content || '（内容加载失败）' });
    } catch {
      setModalDoc({ title: src.title, content: '（无法加载文档内容，请在知识库面板中查看）' });
    } finally {
      setLoadingId(null);
    }
  };

  const typeIcon: Record<string, string> = { knowledge: '📚', order: '🧾', product: '👗' };
  const typeColor: Record<string, string> = {
    knowledge: 'rgba(6,182,212,0.15)',
    order: 'rgba(16,185,129,0.15)',
    product: 'rgba(59,130,246,0.15)',
  };
  const typeBorder: Record<string, string> = {
    knowledge: 'rgba(6,182,212,0.35)',
    order: 'rgba(16,185,129,0.35)',
    product: 'rgba(59,130,246,0.35)',
  };
  const typeTextColor: Record<string, string> = {
    knowledge: '#06B6D4',
    order: '#10B981',
    product: '#3B82F6',
  };

  return (
    <>
      <div className="flex flex-wrap gap-1 mt-1.5 px-1">
        {sources.map((src, si) => (
          <button
            key={si}
            onClick={() => src.type === 'knowledge' ? openKnowledgeDoc(src) : undefined}
            className="text-[9px] px-2 py-0.5 rounded-full border font-semibold flex items-center gap-1 transition-opacity"
            style={{
              background: typeColor[src.type] ?? 'rgba(255,255,255,0.08)',
              borderColor: typeBorder[src.type] ?? 'rgba(255,255,255,0.15)',
              color: typeTextColor[src.type] ?? 'var(--color-muted)',
              cursor: src.type === 'knowledge' ? 'pointer' : 'default',
              opacity: loadingId === src.id ? 0.5 : 1,
            }}
            title={src.type === 'knowledge' ? '点击查看原文' : src.title}>
            {typeIcon[src.type] ?? '📎'} {src.title}
            {src.knowledge_type === 'business_policy' && (
              <span style={{ color: '#F59E0B', fontSize: '8px' }}>POLICY</span>
            )}
          </button>
        ))}
      </div>

      {/* Knowledge doc modal */}
      {modalDoc && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center"
          style={{ background: 'rgba(0,0,0,0.6)' }}
          onClick={() => setModalDoc(null)}>
          <div
            className="rounded-2xl p-6 max-w-lg w-full mx-4 flex flex-col gap-4"
            style={{ background: 'var(--color-surface-2)', border: '1px solid var(--color-border)', maxHeight: '80vh' }}
            onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-bold" style={{ color: 'var(--color-text)' }}>{modalDoc.title}</h3>
              <button onClick={() => setModalDoc(null)} style={{ color: 'var(--color-muted)', cursor: 'pointer' }}>✕</button>
            </div>
            <div className="overflow-y-auto flex-1 text-[12px] leading-relaxed whitespace-pre-wrap"
                 style={{ color: 'var(--color-text)' }}>
              {modalDoc.content}
            </div>
          </div>
        </div>
      )}
    </>
  );
}

// ─── conversation panel ───────────────────────────────────────────────────────

function ConversationPanel({ session, myAgentId, onSend, onResolve, onTyping }: {
  session: SessionInfo | null;
  myAgentId: string;
  onSend: (content: string) => void;
  onResolve: () => void;
  onTyping?: (sessionId: string, typing: boolean) => void;
}) {
  const [reply, setReply] = useState('');
  const [showCustomerPreview, setShowCustomerPreview] = useState(false);
  const [showCanned, setShowCanned] = useState(false);
  const [showKBSearch, setShowKBSearch] = useState(false);
  const [showNoteInput, setShowNoteInput] = useState(false);
  const [noteText, setNoteText] = useState('');
  const [noteSaving, setNoteSaving] = useState(false);
  const [noteToast, setNoteToast] = useState('');
  const [kbQuery, setKBQuery] = useState('');
  const [kbResults, setKBResults] = useState<KBSearchResult[]>([]);
  const [kbLoading, setKBLoading] = useState(false);
  const typingTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const kbTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Reset preview when active session changes
  useEffect(() => {
    setShowCustomerPreview(false); setShowKBSearch(false);
    setShowCanned(false); setShowNoteInput(false); setNoteText('');
  }, [session?.session_id]);

  // Debounced KB search
  useEffect(() => {
    if (!kbQuery.trim()) { setKBResults([]); return; }
    if (kbTimer.current) clearTimeout(kbTimer.current);
    kbTimer.current = setTimeout(async () => {
      setKBLoading(true);
      try {
        const res = await agentKnowledgeSearch(kbQuery);
        setKBResults(res);
      } catch { setKBResults([]); }
      finally { setKBLoading(false); }
    }, 350);
    return () => { if (kbTimer.current) clearTimeout(kbTimer.current); };
  }, [kbQuery]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [session?.history.length]);

  const handleSaveNote = async () => {
    if (!session || !noteText.trim() || noteSaving) return;
    setNoteSaving(true);
    try {
      await addSessionNote(session.session_id, noteText.trim(), myAgentId);
      setNoteText('');
      setShowNoteInput(false);
      setNoteToast('备注已保存');
      setTimeout(() => setNoteToast(''), 2500);
    } catch {
      setNoteToast('保存失败，请重试');
      setTimeout(() => setNoteToast(''), 2500);
    } finally {
      setNoteSaving(false);
    }
  };

  if (!session) {
    return (
      <section className="flex flex-col items-center justify-center h-full gap-4" style={{ opacity: 0.08 }}>
        <div className="w-20 h-20 rounded-full border-2 border-dashed animate-spin"
             style={{ borderColor: 'var(--color-text)', animationDuration: '8s' }} />
        <span className="text-sm uppercase tracking-[0.4em]">等待选择会话</span>
      </section>
    );
  }

  const canReply = session.mode === 'human';
  // Read-only if session is claimed by another agent
  const claimedByOther = !!(session.assigned_agent_id && session.assigned_agent_id !== myAgentId);
  // Read-only if viewing an AI-handled session (monitoring mode)
  const isAiMonitor = session.mode === 'ai';

  return (
    <section className="relative flex flex-col overflow-hidden h-full">
      {/* Customer view preview overlay — pure UI, session data already loaded, no new socket join */}
      <AnimatePresence>
        {showCustomerPreview && (
          <motion.div key="customer-preview"
            initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 20 }} transition={{ duration: 0.15 }}
            className="absolute inset-0 z-20">
            <CustomerChatPreview session={session} onClose={() => setShowCustomerPreview(false)} />
          </motion.div>
        )}
      </AnimatePresence>

      {/* Header */}
      <div className="px-5 pt-3 pb-0 border-b flex flex-col gap-0"
           style={{ borderColor: 'var(--color-border)' }}>
        {/* Row 1: user ID + mode + action buttons */}
        <div className="flex items-center gap-3 pb-2.5">
          <div className="flex-1 min-w-0">
            <div className="text-sm font-semibold truncate">{session.user_id}</div>
            <div className="text-[10px] font-mono" style={{ color: 'var(--color-muted)' }}>
              {session.session_id}
            </div>
          </div>
          <ModeChip mode={session.mode} />
          {/* Resolve (结单) — solid green, clearly a primary action button */}
          {session.mode === 'human' && (
            <button
              onClick={onResolve}
              title="结单并关闭此工单"
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[10px] font-bold transition-all active:scale-[0.96] hover:opacity-90"
              style={{ background: 'var(--color-green)', color: '#0B1220', boxShadow: '0 2px 8px rgba(16,185,129,0.4)' }}>
              <TicketCheck size={10} /> 结单
            </button>
          )}
          {/* Customer view preview — ghost button, secondary, clearly labelled as view-only */}
          <button
            onClick={() => setShowCustomerPreview(true)}
            title="以客户视角预览对话（只读，不发消息）"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[10px] font-bold transition-all active:scale-[0.96] hover:opacity-80"
            style={{ border: '1px solid var(--color-border)', color: 'var(--color-muted)', background: 'var(--color-surface-2)' }}>
            <MessageCircle size={10} /> 客户视角
          </button>
        </div>
        {/* Row 2: metadata info bar */}
        {(() => {
          const flags = computeFlags(session);
          const waitStr = formatWait(flags.lastUserMsg?.timestamp);
          const oc = session.order_context;
          const chips: React.ReactNode[] = [];

          // Sentiment
          if (flags.negative)
            chips.push(
              <span key="neg" className="flex items-center gap-1 text-[10px] font-semibold"
                    style={{ color: 'var(--color-rose)' }}>
                <Frown size={10} /> 负面情绪
              </span>
            );

          // Wedding urgency
          if (flags.urgent && flags.days !== null)
            chips.push(
              <span key="urg" className="flex items-center gap-1 text-[10px] font-semibold"
                    style={{ color: 'var(--color-amber)' }}>
                <AlertTriangle size={10} /> 婚礼剩 {flags.days} 天
              </span>
            );

          // Wait time
          if (waitStr)
            chips.push(
              <span key="wait" className="flex items-center gap-1 text-[10px]"
                    style={{ color: flags.longWait ? 'var(--color-rose)' : 'var(--color-muted)' }}>
                <Clock size={10} /> 等待 {waitStr}
              </span>
            );

          // Order
          if (oc?.order_id)
            chips.push(
              <span key="order" className="flex items-center gap-1 text-[10px]"
                    style={{ color: 'var(--color-muted)' }}>
                <Package size={10} />
                <span className="font-mono">{oc.order_id}</span>
                {oc.total ? <span>¥{oc.total.toLocaleString()}</span> : null}
              </span>
            );

          // Assigned agent
          if (session.assigned_agent_id)
            chips.push(
              <span key="agent" className="flex items-center gap-1 text-[10px]"
                    style={{ color: 'var(--color-green)' }}>
                <UserCheck size={10} /> {session.assigned_agent_id === myAgentId ? '你' : session.assigned_agent_id}
              </span>
            );

          if (chips.length === 0) return null;

          return (
            <div className="flex items-center gap-3 pb-2 flex-wrap"
                 style={{ borderTop: '1px dashed var(--color-border)', paddingTop: '6px', marginTop: '-2px' }}>
              {chips.map((c, i) => (
                <React.Fragment key={i}>
                  {i > 0 && <span style={{ color: 'var(--color-border)', fontSize: '8px' }}>·</span>}
                  {c}
                </React.Fragment>
              ))}
            </div>
          );
        })()}
      </div>

      {/* AI handoff summary — pinned between header and messages, never scrolls away */}
      {(() => {
        const AI_SUMMARY_PREFIX = '[AI 接管摘要]\n';
        const summaryMsg = [...session.history].reverse().find(
          m => m.role === 'system' && m.content.startsWith(AI_SUMMARY_PREFIX)
        );
        if (!summaryMsg) return null;
        const summaryText = summaryMsg.content.slice(AI_SUMMARY_PREFIX.length).trim();
        return (
          <div className="shrink-0 mx-5 mt-1 mb-0 rounded-xl border px-4 py-2.5"
               style={{ background: 'rgba(245,158,11,0.06)', borderColor: 'rgba(245,158,11,0.28)' }}>
            <div className="flex items-center gap-1.5 mb-1">
              <span style={{ color: 'var(--color-amber)', fontSize: '10px' }}>✦</span>
              <span className="text-[10px] font-bold uppercase tracking-widest" style={{ color: 'var(--color-amber)' }}>AI 接管摘要</span>
              <span className="ml-auto text-[9px]" style={{ color: 'var(--color-muted)' }}>仅客服可见</span>
            </div>
            <p className="text-[12px] leading-relaxed whitespace-pre-wrap" style={{ color: 'var(--color-text)', opacity: 0.85 }}>
              {summaryText}
            </p>
          </div>
        );
      })()}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">

        <AnimatePresence initial={false}>
          {session.history.map((msg, i) => {
            // Internal agent notes — sticky note style, never shown to customers
            if (msg.role === 'note') {
              return (
                <motion.div key={i} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}
                  className="flex justify-center py-1">
                  <div className="flex items-start gap-2 px-3 py-2 rounded-xl max-w-[82%]"
                       style={{ background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.25)' }}>
                    <StickyNote size={10} style={{ color: '#f59e0b', flexShrink: 0, marginTop: 2 }} />
                    <div>
                      <div className="text-[9px] font-bold uppercase tracking-widest mb-0.5"
                           style={{ color: '#f59e0b' }}>
                        内部备注 · {msg.agent_id || '客服'}
                      </div>
                      <p className="text-[11px] leading-relaxed whitespace-pre-wrap"
                         style={{ color: 'var(--color-text)', opacity: 0.85 }}>{msg.content}</p>
                    </div>
                  </div>
                </motion.div>
              );
            }
            // System messages: internal-only label, never shown to customers
            if (msg.role === 'system') {
              // Hide the AI summary from inline message list (shown in card above)
              if (msg.content.startsWith('[AI 接管摘要]\n')) return null;
              return (
                <motion.div key={i} initial={{ opacity: 0 }} animate={{ opacity: 1 }}
                  className="flex items-center justify-center gap-2 py-1">
                  <span className="text-[10px] px-2.5 py-0.5 rounded-full border italic"
                        style={{ color: 'var(--color-muted)', borderColor: 'var(--color-border)', background: 'var(--color-surface-2)', opacity: 0.7 }}>
                    {msg.content}
                  </span>
                </motion.div>
              );
            }
            return (
              <motion.div key={i}
                initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
                className={`flex ${msg.role === 'agent' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[78%] ${msg.role === 'agent' ? 'items-end' : 'items-start'} flex flex-col`}>
                  <div className={`text-[9px] uppercase tracking-widest mb-1.5 font-bold px-1 font-mono ${msg.role === 'agent' ? 'text-right' : ''}`}
                       style={{ color: roleColor(msg.role) }}>
                    {msg.role === 'user' ? session.user_id : roleLabel(msg.role)}
                  </div>
                  <div className="px-4 py-2.5 text-[13px] leading-relaxed prose-bubble"
                       style={{
                         background: roleBg(msg.role),
                         color: msg.role === 'agent' ? '#fff' : 'var(--color-text)',
                         borderRadius: msg.role === 'agent' ? '18px 18px 4px 18px' : '18px 18px 18px 4px',
                       }}>
                    <MsgContent content={msg.content} />
                  </div>
                  {/* F6: Source citation chips — only for bot messages with sources */}
                  {msg.role === 'bot' && msg.sources && msg.sources.length > 0 && (
                    <SourceCitations sources={msg.sources} />
                  )}
                </div>
              </motion.div>
            );
          })}
        </AnimatePresence>
        <div ref={bottomRef} />
      </div>

      {/* Input + Tools */}
      <div className="px-4 py-3 border-t flex flex-col gap-2" style={{ borderColor: 'var(--color-border)' }}>

        {/* KB Search panel */}
        {showKBSearch && canReply && !claimedByOther && (
          <div className="rounded-lg border flex flex-col gap-2 p-2.5 text-xs"
               style={{ background: 'rgba(16,185,129,0.05)', borderColor: 'rgba(16,185,129,0.25)' }}>
            <div className="flex items-center gap-2">
              <BookOpen size={11} style={{ color: '#10b981', flexShrink: 0 }} />
              <input
                autoFocus
                value={kbQuery}
                onChange={e => setKBQuery(e.target.value)}
                placeholder="搜索知识库…退货政策、尺码、加急"
                className="flex-1 bg-transparent outline-none text-xs"
                style={{ color: 'var(--color-text)' }}
              />
              {kbLoading && <Loader2 size={11} className="animate-spin" style={{ color: '#10b981' }} />}
            </div>
            {kbResults.length > 0 && (
              <div className="flex flex-col gap-1 max-h-48 overflow-y-auto">
                {kbResults.map(r => (
                  <button
                    key={r.doc_id}
                    onClick={() => {
                      setReply(prev => prev ? `${prev}\n\n${r.snippet}` : r.snippet);
                      setShowKBSearch(false);
                      setKBQuery('');
                      setKBResults([]);
                    }}
                    className="text-left p-2 rounded-md hover:bg-white/5 transition-colors"
                  >
                    <div className="flex items-center gap-1.5 mb-0.5">
                      <span className="font-semibold text-[11px]" style={{ color: 'var(--color-text)' }}>{r.title || '无标题'}</span>
                      <span className="text-[9px] px-1 rounded" style={{
                        background: r.knowledge_type === 'business_policy' ? 'rgba(239,68,68,0.15)' : 'rgba(99,102,241,0.15)',
                        color: r.knowledge_type === 'business_policy' ? '#f87171' : '#818cf8',
                      }}>
                        {r.knowledge_type === 'business_policy' ? '政策' : '知识'}
                      </span>
                    </div>
                    <p className="text-[10px] leading-relaxed line-clamp-2" style={{ color: 'var(--color-muted)' }}>{r.snippet}</p>
                  </button>
                ))}
              </div>
            )}
            {kbQuery.trim() && !kbLoading && kbResults.length === 0 && (
              <p className="text-[10px] text-center py-1" style={{ color: 'var(--color-muted)' }}>无相关文档</p>
            )}
          </div>
        )}

        {/* Canned replies */}
        {showCanned && canReply && !claimedByOther && (
          <div className="flex flex-wrap gap-1.5">
            {CANNED_REPLIES.map(c => (
              <button
                key={c.label}
                onClick={() => { setReply(c.text); setShowCanned(false); }}
                className="text-[10px] px-2 py-1 rounded-md transition-all hover:opacity-80"
                style={{ background: 'rgba(99,102,241,0.12)', color: '#818cf8', border: '1px solid rgba(99,102,241,0.2)' }}
              >
                {c.label}
              </button>
            ))}
          </div>
        )}

        {/* Note input panel */}
        {showNoteInput && (
          <div className="rounded-lg border flex flex-col gap-2 p-2.5 text-xs"
               style={{ background: 'rgba(245,158,11,0.05)', borderColor: 'rgba(245,158,11,0.25)' }}>
            <div className="flex items-center gap-1.5">
              <StickyNote size={11} style={{ color: '#f59e0b' }} />
              <span className="text-[10px] font-bold uppercase tracking-widest" style={{ color: '#f59e0b' }}>内部备注（客户不可见）</span>
            </div>
            <textarea
              autoFocus
              rows={2}
              value={noteText}
              onChange={e => setNoteText(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSaveNote(); } }}
              placeholder="记录处理进展、客户特殊情况、交接说明…"
              className="w-full bg-transparent outline-none resize-none text-xs leading-relaxed"
              style={{ color: 'var(--color-text)' }}
            />
            <div className="flex justify-end gap-2">
              <button onClick={() => { setShowNoteInput(false); setNoteText(''); }}
                className="text-[10px] px-2 py-1 rounded-md" style={{ color: 'var(--color-muted)' }}>
                取消
              </button>
              <button onClick={handleSaveNote} disabled={!noteText.trim() || noteSaving}
                className="flex items-center gap-1 text-[10px] px-2.5 py-1 rounded-md disabled:opacity-40 transition-all"
                style={{ background: 'rgba(245,158,11,0.2)', color: '#f59e0b', border: '1px solid rgba(245,158,11,0.3)' }}>
                {noteSaving ? <Loader2 size={10} className="animate-spin" /> : <StickyNote size={10} />}
                保存备注
              </button>
            </div>
          </div>
        )}

        {noteToast && (
          <div className="text-center text-[10px] py-1 rounded-md"
               style={{ background: 'rgba(245,158,11,0.1)', color: '#f59e0b' }}>
            {noteToast}
          </div>
        )}

        {isAiMonitor ? (
          <div className="rounded-lg border px-3 py-2.5 text-[11px] leading-relaxed"
               style={{ background: 'rgba(59,130,246,0.06)', borderColor: 'rgba(59,130,246,0.25)', color: 'var(--color-muted)' }}>
            <span className="font-bold" style={{ color: 'var(--color-blue)' }}>👁 AI 处理中（只读）</span>
            <span className="mx-1">—</span>
            当前由 AI 自动服务，你可在左侧列表点击
            <strong style={{ color: 'var(--color-amber)' }}>「⚡ 接管此会话」</strong>
            切换为人工接待。
          </div>
        ) : canReply && !claimedByOther ? (
          <div className="flex flex-col gap-1.5">
            {/* Toolbar row */}
            <div className="flex items-center gap-1">
              <button
                onClick={() => { setShowKBSearch(v => !v); setShowCanned(false); setShowNoteInput(false); }}
                title="搜索知识库"
                className="flex items-center gap-1 text-[10px] px-2 py-1 rounded-md transition-all"
                style={{
                  background: showKBSearch ? 'rgba(16,185,129,0.15)' : 'transparent',
                  color: showKBSearch ? '#10b981' : 'var(--color-muted)',
                  border: `1px solid ${showKBSearch ? 'rgba(16,185,129,0.3)' : 'var(--color-border)'}`,
                }}
              >
                <BookOpen size={10} /> 知识库
              </button>
              <button
                onClick={() => { setShowCanned(v => !v); setShowKBSearch(false); setShowNoteInput(false); }}
                title="快捷回复"
                className="flex items-center gap-1 text-[10px] px-2 py-1 rounded-md transition-all"
                style={{
                  background: showCanned ? 'rgba(99,102,241,0.15)' : 'transparent',
                  color: showCanned ? '#818cf8' : 'var(--color-muted)',
                  border: `1px solid ${showCanned ? 'rgba(99,102,241,0.3)' : 'var(--color-border)'}`,
                }}
              >
                <Sparkles size={10} /> 快捷回复
              </button>
              <button
                onClick={() => { setShowNoteInput(v => !v); setShowCanned(false); setShowKBSearch(false); }}
                title="添加内部备注"
                className="flex items-center gap-1 text-[10px] px-2 py-1 rounded-md transition-all"
                style={{
                  background: showNoteInput ? 'rgba(245,158,11,0.15)' : 'transparent',
                  color: showNoteInput ? '#f59e0b' : 'var(--color-muted)',
                  border: `1px solid ${showNoteInput ? 'rgba(245,158,11,0.3)' : 'var(--color-border)'}`,
                }}
              >
                <StickyNote size={10} /> 备注
              </button>
            </div>
            {/* Input row */}
            <div className="flex gap-2 rounded-lg border p-2"
                 style={{ background: 'var(--color-surface-2)', borderColor: 'var(--color-border)' }}>
              <textarea
                rows={reply.split('\n').length > 2 ? 3 : 1}
                value={reply}
                onChange={e => {
                  const val = e.target.value;
                  setReply(val);
                  // "/" at the very start of an empty box opens canned replies
                  if (val === '/') { setShowCanned(true); setReply(''); setShowKBSearch(false); setShowNoteInput(false); }
                  if (session && onTyping) {
                    onTyping(session.session_id, true);
                    if (typingTimer.current) clearTimeout(typingTimer.current);
                    typingTimer.current = setTimeout(() => onTyping(session.session_id, false), 2000);
                  }
                }}
                onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); if (reply.trim()) { onSend(reply); setReply(''); if (session && onTyping) onTyping(session.session_id, false); } } }}
                placeholder="以顾问身份回复客户… (Enter 发送 · / 快捷话术)"
                className="flex-1 bg-transparent text-sm outline-none placeholder:opacity-30 resize-none"
                style={{ color: 'var(--color-text)', minHeight: 24 }}
              />
              <button onClick={() => { if (reply.trim()) { onSend(reply); setReply(''); if (session && onTyping) onTyping(session.session_id, false); } }}
                disabled={!reply.trim()}
                className="px-4 py-1.5 rounded-md text-xs font-bold disabled:opacity-20 transition-all self-end"
                style={{ background: 'var(--color-blue)', color: '#fff' }}>
                <Send size={13} />
              </button>
            </div>
          </div>
        ) : claimedByOther ? (
          <div className="text-center text-[11px] py-1.5 rounded-md"
               style={{ background: 'var(--color-surface-2)', color: 'var(--color-muted)' }}>
            🔒 已由 <span className="font-semibold" style={{ color: 'var(--color-text)' }}>{session.assigned_agent_id}</span> 认领，只读模式
          </div>
        ) : (
          <div className="text-center text-[11px] py-1.5 rounded-md"
               style={{ background: 'var(--color-surface-2)', color: 'var(--color-muted)' }}>
            {session.mode === 'hitl_pending'
              ? '⏳ 等待 HITL 审批，请在右侧面板操作'
              : '🤖 AI 自动处理中'}
          </div>
        )}
      </div>
    </section>
  );
}

// ─── AgentWorkspace root ──────────────────────────────────────────────────────

export default function AgentWorkspace({
  focusSessionId,
}: {
  focusSessionId?: string | null;
}) {
  const [queue, setQueue]               = useState<SessionInfo[]>([]);
  const [allSessions, setAllSessions]   = useState<SessionInfo[]>([]);
  const [activeSession, setActiveSession] = useState<SessionInfo | null>(null);
  const [connected, setConnected]       = useState(false);
  const [showResolve, setShowResolve]   = useState(false);
  const [showHistory, setShowHistory]   = useState(false);
  const [showAnalytics, setShowAnalytics] = useState(false);
  // Mobile: which column is visible
  const [mobileTab, setMobileTab] = useState<'queue' | 'chat' | 'context'>('queue');
  // Agent identity — null until login
  const [myAgentId, setMyAgentId]       = useState<string | null>(null);
  const [myName, setMyName]             = useState<string>('');
  const [onlineAgents, setOnlineAgents] = useState<AgentInfo[]>([]);
  // SLA warnings: session_id → message
  const [slaWarnings, setSlaWarnings]   = useState<Record<string, string>>({});
  // F: Unread message counts per session
  const [unreadCounts, setUnreadCounts] = useState<Record<string, number>>({});
  // D: Customer typing indicators: session_id → typing
  const [customerTyping, setCustomerTyping] = useState<Record<string, boolean>>({});
  const activeSessionIdRef = useRef<string | null>(null);
  useEffect(() => { activeSessionIdRef.current = activeSession?.session_id ?? null; }, [activeSession]);
  // Stable ref to queue for use inside callbacks without stale closure
  const queueRef = useRef<SessionInfo[]>([]);
  useEffect(() => { queueRef.current = queue; }, [queue]);
  // Stable ref to allSessions for use inside callbacks (AI-mode sessions not in queue)
  const allSessionsRef = useRef<SessionInfo[]>([]);
  useEffect(() => { allSessionsRef.current = allSessions; }, [allSessions]);
  // I8: Track previous queue session IDs for push notification diff
  const prevQueueRef = useRef<Set<string>>(new Set());
  // M2: Today stats for header stats strip
  const [todayStats, setTodayStats] = useState<{total_sessions:number, ai_resolved:number, escalated_to_human:number, resolved:number} | null>(null);

  // ── agent login ──────────────────────────────────────────────────────────────
  const handleLogin = (id: string, name: string) => {
    setMyAgentId(id);
    setMyName(name);
    socket.emit('join_workspace', { agent_id: id, name }, (resp: { queue: SessionInfo[]; all_sessions?: SessionInfo[] }) => {
      if (resp?.queue) setQueue(resp.queue);
      // Populate allSessions with existing AI-mode sessions so they're visible immediately
      if (resp?.all_sessions) setAllSessions(resp.all_sessions);
    });
  };

  // I8: Request notification permission once after agent login
  useEffect(() => {
    if (!myAgentId) return;
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission();
    }
  }, [myAgentId]);

  // ── socket events ────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!myAgentId) return;   // wait until login
    if (socket.connected) setConnected(true);

    const onConnect    = () => setConnected(true);
    const onDisconnect = () => setConnected(false);

    const onQueueUpdated = (updated: SessionInfo[]) => {
      setQueue(updated);
      // Sync active session: if it left the queue (e.g. HITL resolved → ai mode),
      // clear it so the panel doesn't show stale hitl_pending state.
      setActiveSession(prev => {
        if (!prev) return prev;
        return updated.find(s => s.session_id === prev.session_id) ?? null;
      });
      // I8: Fire browser push notification for new hitl_pending sessions
      const newHitl = updated.filter(
        (s: SessionInfo) => s.mode === 'hitl_pending' && !prevQueueRef.current.has(s.session_id)
      );
      newHitl.forEach((s: SessionInfo) => {
        if (Notification.permission === 'granted') {
          new Notification('⚡ 新 HITL 审批请求', {
            body: `客户 ${s.user_id} 的操作需要确认`,
            icon: '/favicon.ico',
          });
        }
      });
      prevQueueRef.current = new Set(updated.map((s: SessionInfo) => s.session_id));
    };

    const onHitlPending = (data: { session_id: string; session: SessionInfo }) => {
      setQueue(prev => {
        const exists = prev.find(s => s.session_id === data.session_id);
        return exists
          ? prev.map(s => s.session_id === data.session_id ? data.session : s)
          : [...prev, data.session];
      });
    };

    const onNewMessage = (data: { session_id: string; msg: ChatMsg }) => {
      const updater = (s: SessionInfo) =>
        s.session_id === data.session_id ? { ...s, history: [...s.history, data.msg] } : s;
      setQueue(prev => prev.map(updater));
      // Also keep active session updated (including AI-mode pinned sessions)
      setActiveSession(prev => prev && prev.session_id === data.session_id ? updater(prev) : prev);
      // F: Increment unread count if this session is not currently active
      if (data.msg.role !== 'system' && data.session_id !== activeSessionIdRef.current) {
        setUnreadCounts(prev => ({ ...prev, [data.session_id]: (prev[data.session_id] ?? 0) + 1 }));
      }
    };

    // D: Customer typing indicator
    const onCustomerTyping = (data: { session_id: string; typing: boolean }) => {
      setCustomerTyping(prev => ({ ...prev, [data.session_id]: data.typing }));
      // Auto-clear after 4s
      if (data.typing) {
        setTimeout(() => setCustomerTyping(prev => ({ ...prev, [data.session_id]: false })), 4000);
      }
    };

    const onTicketResolved = (data: { session_id: string }) => {
      setQueue(prev => prev.filter(s => s.session_id !== data.session_id));
      setActiveSession(prev => prev?.session_id === data.session_id ? null : prev);
    };

    const onSessionClaimed = (data: { session_id: string; agent_id: string }) => {
      // Update assigned_agent_id on the session in queue
      const update = (s: SessionInfo) =>
        s.session_id === data.session_id
          ? { ...s, assigned_agent_id: data.agent_id }
          : s;
      setQueue(prev => prev.map(update));
      setActiveSession(prev => prev?.session_id === data.session_id ? update(prev) : prev);
    };

    const onAgentJoined = (data: AgentInfo) => {
      setOnlineAgents(prev => {
        const filtered = prev.filter(a => a.agent_id !== data.agent_id);
        return [...filtered, { ...data, status: 'online' as const }];
      });
    };

    const onAgentLeft = (data: { agent_id: string; name: string }) => {
      setOnlineAgents(prev => prev.filter(a => a.agent_id !== data.agent_id));
    };

    const onSlaWarning = (data: { session_id: string; message: string }) => {
      setSlaWarnings(prev => ({ ...prev, [data.session_id]: data.message }));
      // Auto-clear after 5 minutes
      setTimeout(() => setSlaWarnings(prev => {
        const next = { ...prev };
        delete next[data.session_id];
        return next;
      }), 300_000);
    };

    const onOrderContextUpdated = (data: { session_id: string; order_context: any }) => {
      const update = (s: SessionInfo) =>
        s.session_id === data.session_id ? { ...s, order_context: data.order_context } : s;
      setQueue(prev => prev.map(update));
      setActiveSession(prev => prev?.session_id === data.session_id ? update(prev) : prev);
    };

    const onAllSessionsUpdated = (sessions: SessionInfo[]) => {
      setAllSessions(sessions);
    };

    socket.on('connect',         onConnect);
    socket.on('disconnect',      onDisconnect);
    socket.on('queue_updated',   onQueueUpdated);
    socket.on('hitl_pending',    onHitlPending);
    socket.on('new_message',     onNewMessage);
    socket.on('ticket_resolved', onTicketResolved);
    socket.on('session_claimed', onSessionClaimed);
    socket.on('agent_joined',          onAgentJoined);
    socket.on('agent_left',            onAgentLeft);
    socket.on('order_context_updated', onOrderContextUpdated);
    socket.on('sla_warning',           onSlaWarning);
    socket.on('customer_typing',       onCustomerTyping);
    socket.on('all_sessions_updated',  onAllSessionsUpdated);

    return () => {
      socket.off('connect',              onConnect);
      socket.off('disconnect',           onDisconnect);
      socket.off('queue_updated',        onQueueUpdated);
      socket.off('hitl_pending',         onHitlPending);
      socket.off('new_message',          onNewMessage);
      socket.off('ticket_resolved',      onTicketResolved);
      socket.off('session_claimed',      onSessionClaimed);
      socket.off('agent_joined',         onAgentJoined);
      socket.off('agent_left',           onAgentLeft);
      socket.off('order_context_updated', onOrderContextUpdated);
      socket.off('sla_warning',           onSlaWarning);
      socket.off('customer_typing',       onCustomerTyping);
      socket.off('all_sessions_updated',  onAllSessionsUpdated);
    };
  }, [myAgentId]);

  // ── auto-focus session coming from CustomerPortal ────────────────────────────
  useEffect(() => {
    if (!focusSessionId) return;

    // Already the active session — nothing to do
    if (activeSession?.session_id === focusSessionId) return;

    // Try the queue first (hitl/human sessions)
    const inQueue = queue.find(s => s.session_id === focusSessionId);
    if (inQueue) {
      setActiveSession(inQueue);
      return;
    }

    // Not in queue (probably an AI-mode session) — fetch it from the server
    socket.emit('get_session', { session_id: focusSessionId }, (sess: SessionInfo | null) => {
      if (sess) setActiveSession(sess);
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusSessionId, queue]);

  // ── handlers ─────────────────────────────────────────────────────────────────
  const handleSelectSession = useCallback((sess: SessionInfo) => {
    setActiveSession(sess);
    // F: Clear unread count on open
    setUnreadCounts(prev => {
      const next = { ...prev };
      delete next[sess.session_id];
      return next;
    });
  }, []);

  const handleSend = (content: string) => {
    if (!activeSession) return;
    // D: Stop typing indicator when message is sent
    socket.emit('agent_typing', { session_id: activeSession.session_id, typing: false });
    socket.emit('agent_reply', {
      session_id: activeSession.session_id,
      content,
      agent_id: myAgentId,
    });
  };

  const handleApprove = () => {
    if (!activeSession) return;
    socket.emit('hitl_approve', { session_id: activeSession.session_id });
  };

  const handleReject = () => {
    if (!activeSession) return;
    socket.emit('hitl_reject', { session_id: activeSession.session_id });
  };

  const handleTransferToAgent = (note: string) => {
    if (!activeSession) return;
    socket.emit('transfer_to_agent', { session_id: activeSession.session_id, note });
  };

  const handleTransferToBot = () => {
    if (!activeSession) return;
    socket.emit('transfer_to_bot', { session_id: activeSession.session_id });
  };

  const handleResolve = () => setShowResolve(true);

  const handleClaim = useCallback((sessionId: string): Promise<{ ok: boolean; message?: string }> => {
    return new Promise(resolve => {
      if (!myAgentId) { resolve({ ok: false, message: '未登录' }); return; }
      // Optimistically open the session so the agent can see it immediately.
      const sess =
        queueRef.current.find(s => s.session_id === sessionId) ||
        allSessionsRef.current.find(s => s.session_id === sessionId);
      if (sess) setActiveSession(sess);
      socket.emit(
        'claim_session',
        { session_id: sessionId, agent_id: myAgentId },
        (resp: { success: boolean; message: string }) => {
          if (!resp?.success) {
            setActiveSession(prev => prev?.session_id === sessionId ? null : prev);
            resolve({ ok: false, message: resp?.message ?? '认领失败' });
          } else {
            if (!sess) {
              socket.emit('get_session', { session_id: sessionId }, (s: SessionInfo | null) => {
                if (s) setActiveSession(s);
              });
            }
            resolve({ ok: true });
          }
        }
      );
    });
  }, [myAgentId]);

  const handleIntervene = useCallback(async (sessionId: string): Promise<{ ok: boolean; message?: string }> => {
    // Step 1: switch session from AI mode → human mode
    socket.emit('transfer_to_agent', { session_id: sessionId });
    // Step 2: claim the session for this agent
    return handleClaim(sessionId);
  }, [handleClaim]);

  // D: Relay agent typing state to customer via socket
  const handleAgentTyping = useCallback((sessionId: string, typing: boolean) => {
    socket.emit('agent_typing', { session_id: sessionId, typing });
  }, []);

  // M2: Fetch today stats for header stats strip
  useEffect(() => {
    if (!myAgentId) return;
    const fetchStats = async () => {
      try {
        const r = await fetch(`${BASE_URL}/api/workspace/metrics/today`);
        if (r.ok) {
          const d = await r.json();
          setTodayStats({
            total_sessions: d.total_sessions ?? 0,
            ai_resolved: d.ai_resolved ?? 0,
            escalated_to_human: d.escalated_to_human ?? 0,
            resolved: d.resolved ?? 0,
          });
        }
      } catch { /* ignore */ }
    };
    fetchStats();
    const id = setInterval(fetchStats, 5 * 60 * 1000);
    return () => clearInterval(id);
  }, [myAgentId]);

  // Show login screen until agent identifies themselves
  if (!myAgentId) {
    return <AgentLoginScreen onLogin={handleLogin} />;
  }

  return (
    <div className="flex flex-col h-screen" style={{ background: 'var(--color-bg)', color: 'var(--color-text)' }}>
      <AnimatePresence>
        {showResolve && activeSession && (
          <ResolveDialog
            sessionId={activeSession.session_id}
            onClose={() => setShowResolve(false)}
            onResolved={() => {
              setQueue(prev => prev.filter(s => s.session_id !== activeSession.session_id));
              setActiveSession(null);
            }}
          />
        )}
      </AnimatePresence>
      {/* Header */}
      <header className="h-14 border-b flex items-center justify-between px-3 md:px-6 shrink-0"
              style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
        <div className="flex items-center gap-2 md:gap-3">
          <div className="w-7 h-7 rounded-md flex items-center justify-center text-sm font-bold shadow-lg"
               style={{ background: 'var(--color-pink)', boxShadow: '0 0 12px var(--color-pink-glow)' }}>💐</div>
          <span className="font-semibold text-sm md:text-base">缘梦婚纱 <span className="hidden md:inline font-light opacity-40 italic text-sm">智能工作台</span></span>
        </div>
        <div className="flex items-center gap-2 md:gap-3 text-[10px]">
          <StatusPill label="实时连接" active={connected} />
          <span className="hidden sm:contents">
          <StatusPill label="HITL 待审批" value={queue.filter(s => s.mode === 'hitl_pending').length} color="var(--color-amber)" />
          <StatusPill label="人工接管"   value={queue.filter(s => s.mode === 'human').length}        color="var(--color-green)" />
          <StatusPill label="客服在线"   value={onlineAgents.length + 1}                             color="var(--color-blue)" />
          </span>
          {/* Current agent identity */}
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-full border"
               style={{ borderColor: 'var(--color-border)', background: 'var(--color-bg)' }}>
            <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: 'var(--color-green)', boxShadow: '0 0 5px var(--color-green)' }} />
            <span style={{ color: 'var(--color-text)' }} className="font-semibold">{myName}</span>
            <span className="font-mono" style={{ color: 'var(--color-muted)', fontSize: '9px' }}>{myAgentId}</span>
          </div>
          {todayStats && (
            <div className="hidden md:flex items-center gap-2 text-[10px] px-3">
              <StatChip label="今日会话" value={todayStats.total_sessions} color="var(--color-blue)" />
              <StatChip label="AI解决" value={todayStats.ai_resolved} color="var(--color-green)" />
              <StatChip label="转人工" value={todayStats.escalated_to_human} color="var(--color-amber)" />
              <StatChip label="已结单" value={todayStats.resolved} color="var(--color-muted)" />
            </div>
          )}
          <button
            onClick={() => { setShowHistory(true); setShowAnalytics(false); }}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-full border font-bold transition-all"
            style={{ borderColor: showHistory ? 'var(--color-blue)' : 'var(--color-border)', color: showHistory ? 'var(--color-blue)' : 'var(--color-muted)', background: 'var(--color-bg)' }}>
            <History size={10} /> 历史
          </button>
          <button
            onClick={() => { setShowAnalytics(true); setShowHistory(false); }}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-full border font-bold transition-all"
            style={{ borderColor: showAnalytics ? 'var(--color-blue)' : 'var(--color-border)', color: showAnalytics ? 'var(--color-blue)' : 'var(--color-muted)', background: 'var(--color-bg)' }}>
            <BarChart3 size={10} /> 数据
          </button>
        </div>
      </header>

      {/* 3-column layout — desktop: CSS grid; mobile: show only active tab column */}
      <main className="flex-1 overflow-hidden workspace-main">
        <style>{`
          .workspace-main {
            display: grid;
            grid-template-columns: 240px 1fr 280px;
            gap: 1px;
            background: var(--color-border);
          }
          .workspace-main > .ws-col { overflow: hidden; background: var(--color-surface); }
          @media (max-width: 767px) {
            .workspace-main {
              display: block;
              background: var(--color-surface);
            }
            .workspace-main > .ws-col { display: none; height: 100%; }
            .workspace-main > .ws-col.active { display: block; }
          }
        `}</style>

        <div className={`ws-col${mobileTab === 'queue' ? ' active' : ''}`}>
          <SessionList
            sessions={queue}
            allSessions={allSessions}
            activeId={activeSession?.session_id ?? null}
            myAgentId={myAgentId}
            slaWarnings={slaWarnings}
            unreadCounts={unreadCounts}
            customerTyping={customerTyping}
            onSelect={(s) => { handleSelectSession(s); setMobileTab('chat'); }}
            onClaim={async (s) => { const r = await handleClaim(s); setMobileTab('chat'); return r; }}
            onIntervene={async (s) => { const r = await handleIntervene(s); setMobileTab('chat'); return r; }}
          />
        </div>
        <div className={`ws-col${mobileTab === 'chat' ? ' active' : ''}`}>
          <ConversationPanel
            session={activeSession}
            myAgentId={myAgentId ?? ''}
            onSend={handleSend}
            onResolve={handleResolve}
            onTyping={handleAgentTyping}
          />
        </div>
        <div className={`ws-col${mobileTab === 'context' ? ' active' : ''}`}>
          <ContextPanel
            session={activeSession}
            onApprove={handleApprove}
            onReject={handleReject}
            onTransferToAgent={handleTransferToAgent}
            onTransferToBot={handleTransferToBot}
          />
        </div>
      </main>

      {/* Mobile bottom tab bar */}
      <nav
        className="flex md:hidden border-t flex-shrink-0"
        style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
      >
        {([
          { id: 'queue',   label: '会话队列', badge: queue.length },
          { id: 'chat',    label: '对话',     badge: activeSession && unreadCounts[activeSession.session_id] ? unreadCounts[activeSession.session_id] : 0 },
          { id: 'context', label: '信息',     badge: queue.filter(s => s.mode === 'hitl_pending').length },
        ] as { id: 'queue' | 'chat' | 'context'; label: string; badge: number }[]).map(tab => (
          <button
            key={tab.id}
            onClick={() => setMobileTab(tab.id)}
            className="flex-1 flex flex-col items-center justify-center py-2 gap-0.5 relative text-[11px] font-medium"
            style={{ color: mobileTab === tab.id ? 'var(--color-blue)' : 'var(--color-muted)' }}
          >
            {tab.label}
            {tab.badge > 0 && (
              <span
                className="absolute top-1.5 right-1/4 text-[9px] px-1 py-0.5 rounded-full font-bold"
                style={{ background: 'var(--color-pink)', color: '#fff', minWidth: 14, textAlign: 'center' }}
              >
                {tab.badge}
              </span>
            )}
            {mobileTab === tab.id && (
              <span className="absolute bottom-0 left-1/4 right-1/4 h-0.5 rounded-full" style={{ background: 'var(--color-blue)' }} />
            )}
          </button>
        ))}
      </nav>

      {/* History panel overlay */}
      <AnimatePresence>
        {showHistory && (
          <HistoryPanel onClose={() => setShowHistory(false)} />
        )}
      </AnimatePresence>

      {/* Analytics panel overlay */}
      <AnimatePresence>
        {showAnalytics && (
          <AnalyticsPanel onClose={() => setShowAnalytics(false)} />
        )}
      </AnimatePresence>
    </div>
  );
}

// ─── micro components ─────────────────────────────────────────────────────────

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border-b p-4 space-y-2" style={{ borderColor: 'var(--color-border)' }}>
      <div className="text-[10px] uppercase tracking-widest font-bold" style={{ color: 'var(--color-muted)' }}>{title}</div>
      {children}
    </div>
  );
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex justify-between items-center">
      <span style={{ color: 'var(--color-muted)' }}>{label}</span>
      <span className={mono ? 'font-mono text-[10px]' : ''}>{value}</span>
    </div>
  );
}

function ActionBtn({ icon, onClick, color, label, disabled }: { icon: React.ReactNode; onClick: () => void; color: string; label: string; disabled?: boolean }) {
  const [hov, setHov] = useState(false);
  return (
    <button
      disabled={disabled}
      onClick={disabled ? undefined : onClick}
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
      className="flex items-center gap-2 px-3 py-2.5 rounded-lg text-[11px] font-bold w-full transition-all active:scale-[0.97]"
      style={{
        border: `1px solid ${color}55`,
        color: hov && !disabled ? '#fff' : color,
        background: disabled ? 'transparent' : hov ? color : `${color}18`,
        opacity: disabled ? 0.4 : 1,
        cursor: disabled ? 'not-allowed' : 'pointer',
        boxShadow: hov && !disabled ? `0 2px 10px ${color}35` : 'none',
      }}>
      {icon}
      <span className="flex-1 text-left">{label}</span>
      {!disabled && <ChevronRight size={10} style={{ opacity: 0.45 }} />}
    </button>
  );
}

function ModeChip({ mode, className }: { mode: string; className?: string }) {
  const b = MODE_BADGE[mode] ?? { label: mode, color: '#64748B' };
  return (
    <span className={`text-[9px] px-2 py-0.5 rounded font-bold border ${className ?? ''}`}
          style={{ color: b.color, borderColor: b.color + '40', background: b.color + '15' }}>
      {b.label}
    </span>
  );
}

function StatusPill({ label, active, value, color }: {
  label: string; active?: boolean; value?: number; color?: string;
}) {
  const isOn = active !== undefined ? active : (value ?? 0) > 0;
  const c = color ?? (isOn ? 'var(--color-green)' : 'var(--color-muted)');
  return (
    <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full border"
         style={{ borderColor: 'var(--color-border)', background: 'var(--color-bg)' }}>
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: c, boxShadow: isOn ? `0 0 6px ${c}` : 'none' }} />
      <span style={{ color: 'var(--color-muted)' }}>{label}</span>
      {value !== undefined && <span className="font-mono font-bold">{value}</span>}
    </div>
  );
}

function StatChip({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="flex items-center gap-1 px-2 py-0.5 rounded border"
         style={{ borderColor: color + '40', background: color + '12' }}>
      <span style={{ color }}>{value}</span>
      <span style={{ color: 'var(--color-muted)' }}>{label}</span>
    </div>
  );
}

function roleColor(role: string): string {
  return { user: 'var(--color-blue)', bot: 'var(--color-pink)', agent: 'var(--color-green)', system: 'var(--color-muted)' }[role] ?? 'var(--color-muted)';
}

function roleLabel(role: string): string {
  return { user: '客户', bot: '客服', agent: '客服', system: '系统' }[role] ?? role;
}

function roleBg(role: string): string {
  return {
    user:   'rgba(59,130,246,0.12)',   // customer — left side, subtle blue tint
    bot:    'var(--color-surface-2)',
    agent:  'rgba(16,185,129,0.88)',   // agent self — right side, solid green
    system: 'var(--color-surface-2)',
  }[role] ?? 'var(--color-surface-2)';
}

// ─── types for history & analytics ───────────────────────────────────────────

interface TicketItem {
  ticket_id: string;
  session_id: string;
  user_id: string;
  status: string;
  category?: string;
  created_at: string;
  resolved_at?: string | null;
  summary?: string | null;
  sentiment?: string | null;
  report_ai_quality?: string | null;
}

interface TicketDetail extends TicketItem {
  resolution?: string | null;
  report_key_issues?: string[] | null;
  report_resolution_type?: string | null;
}

interface HistoryMessage {
  role: string;
  content: string;
  created_at: string;
  node_name?: string | null;
}

interface AnalyticsData {
  period_days: number;
  total_sessions: number;
  ai_resolved: number;
  escalated_to_human: number;
  hitl_count: number;
  avg_bot_response_ms: number;
  top_intents: { intent: string; count: number }[];
  resolved_count: number;
  open_count: number;
  category_distribution?: { category: string; count: number }[];
  escalation_by_node?: { node: string; count: number }[];
  daily_volume?: { date: string; count: number }[];
  csat?: { avg_rating: number | null; count: number };
  avg_resolution_minutes?: number | null;
}

interface TodayMetrics {
  date: string;
  total_sessions: number;
  ai_resolved: number;
  escalated_to_human: number;
  hitl_approvals: number;
  hitl_rejections: number;
  avg_first_response_ms: number;
  resolved_count: number;
}

const BASE_URL = 'http://localhost:8000';
const fmtDate = (d: string) => new Date(d).toLocaleString('zh-CN', { hour12: false });

// ─── HistoryPanel ─────────────────────────────────────────────────────────────

function SentimentIcon({ sentiment }: { sentiment?: string | null }) {
  if (sentiment === 'positive') return <ThumbsUp size={11} style={{ color: 'var(--color-green)' }} />;
  if (sentiment === 'negative') return <ThumbsDown size={11} style={{ color: 'var(--color-rose)' }} />;
  return <Minus size={11} style={{ color: 'var(--color-muted)' }} />;
}

function AiQualityBadge({ quality }: { quality?: string | null }) {
  if (!quality) return null;
  const map: Record<string, { color: string; label: string }> = {
    good:    { color: 'var(--color-green)', label: '优' },
    ok:      { color: 'var(--color-amber)', label: '良' },
    poor:    { color: 'var(--color-rose)',  label: '差' },
  };
  const style = map[quality] ?? { color: 'var(--color-muted)', label: quality };
  return (
    <span className="text-[9px] px-1.5 py-0.5 rounded font-bold border"
          style={{ color: style.color, borderColor: style.color + '40', background: style.color + '15' }}>
      AI {style.label}
    </span>
  );
}

function HistoryPanel({ onClose }: { onClose: () => void }) {
  const [tickets, setTickets]           = useState<TicketItem[]>([]);
  const [loading, setLoading]           = useState(false);
  const [statusFilter, setStatusFilter] = useState('');
  const [dateFrom, setDateFrom]         = useState('');
  const [filterCategory, setFilterCategory] = useState('');
  const [search, setSearch]             = useState('');
  const [selectedTicket, setSelectedTicket] = useState<TicketDetail | null>(null);
  const [detailLoading, setDetailLoading]   = useState(false);
  const [messages, setMessages]             = useState<HistoryMessage[]>([]);
  const [msgLoading, setMsgLoading]         = useState(false);

  const fetchTickets = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (statusFilter) params.set('status', statusFilter);
      if (dateFrom)     params.set('date_from', dateFrom);
      params.set('limit', '50');
      const res = await fetch(`${BASE_URL}/api/workspace/tickets?${params}`);
      if (res.ok) {
        const data = await res.json();
        setTickets(Array.isArray(data) ? data : (data.tickets ?? []));
      }
    } catch { /* ignore */ }
    setLoading(false);
  }, [statusFilter, dateFrom]);

  useEffect(() => { fetchTickets(); }, [fetchTickets]);

  const handleRowClick = async (ticket: TicketItem) => {
    setDetailLoading(true);
    setMessages([]);
    try {
      const res = await fetch(`${BASE_URL}/api/workspace/tickets/${ticket.ticket_id}`);
      if (res.ok) setSelectedTicket(await res.json());
    } catch { /* ignore */ }
    setDetailLoading(false);
    // Load messages — API returns { session_id, ticket, messages: [...], status_timeline: [...] }
    setMsgLoading(true);
    try {
      const res = await fetch(`${BASE_URL}/api/workspace/sessions/${ticket.session_id}/messages`);
      if (res.ok) {
        const data = await res.json();
        setMessages(Array.isArray(data) ? data : (data.messages ?? []));
      }
    } catch { /* ignore */ }
    setMsgLoading(false);
  };

  const filtered = tickets.filter(t => {
    if (filterCategory && t.category !== filterCategory) return false;
    if (!search) return true;
    const q = search.toLowerCase();
    return t.ticket_id.toLowerCase().includes(q) || t.user_id.toLowerCase().includes(q);
  });

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-40 flex flex-col"
      style={{ background: 'var(--color-bg)', color: 'var(--color-text)' }}>

      {/* Panel header */}
      <div className="h-14 border-b flex items-center gap-3 px-6 shrink-0"
           style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
        <History size={16} style={{ color: 'var(--color-blue)' }} />
        <span className="font-semibold">历史工单</span>
        <div className="flex-1" />
        <button onClick={onClose}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-[11px] font-bold transition-all"
          style={{ borderColor: 'var(--color-border)', color: 'var(--color-muted)', background: 'var(--color-bg)' }}>
          <X size={11} /> 关闭
        </button>
      </div>

      {/* Filter bar */}
      <div className="flex items-center gap-3 px-6 py-3 border-b shrink-0"
           style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
        <select
          value={statusFilter}
          onChange={e => setStatusFilter(e.target.value)}
          className="rounded-lg border px-2 py-1.5 text-[12px] outline-none"
          style={{ background: 'var(--color-surface-2)', borderColor: 'var(--color-border)', color: 'var(--color-text)' }}>
          <option value="">全部状态</option>
          <option value="resolved">已结单</option>
          <option value="open">处理中</option>
        </select>
        <input
          type="date"
          value={dateFrom}
          onChange={e => setDateFrom(e.target.value)}
          className="rounded-lg border px-2 py-1.5 text-[12px] outline-none"
          style={{ background: 'var(--color-surface-2)', borderColor: 'var(--color-border)', color: 'var(--color-text)' }}
        />
        <select
          value={filterCategory}
          onChange={e => setFilterCategory(e.target.value)}
          className="px-2 py-1 rounded text-[11px] border"
          style={{ background: 'var(--color-surface-2)', borderColor: 'var(--color-border)', color: 'var(--color-text)' }}>
          <option value="">全部分类</option>
          {['订单查询','产品咨询','质量投诉','退换货','加急制作','价格咨询','配送问题','其他'].map(c => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
        <input
          type="text"
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="搜索客户ID或工单号…"
          className="flex-1 rounded-lg border px-3 py-1.5 text-[12px] outline-none"
          style={{ background: 'var(--color-surface-2)', borderColor: 'var(--color-border)', color: 'var(--color-text)' }}
        />
      </div>

      {/* Body: list + detail */}
      <div className="flex-1 flex overflow-hidden">
        {/* Ticket list */}
        <div className="w-[480px] shrink-0 border-r overflow-y-auto"
             style={{ borderColor: 'var(--color-border)' }}>
          {loading && (
            <div className="p-6 text-center text-[11px] italic" style={{ color: 'var(--color-muted)' }}>加载中…</div>
          )}
          {!loading && filtered.length === 0 && (
            <div className="p-6 text-center text-[11px] italic" style={{ color: 'var(--color-muted)', opacity: 0.5 }}>暂无工单</div>
          )}
          {filtered.map(ticket => (
            <div
              key={ticket.ticket_id}
              onClick={() => handleRowClick(ticket)}
              className="p-4 border-b cursor-pointer transition-all"
              style={{
                borderColor: 'var(--color-border)',
                background: selectedTicket?.ticket_id === ticket.ticket_id ? 'var(--color-surface-2)' : 'transparent',
                borderLeft: selectedTicket?.ticket_id === ticket.ticket_id ? '3px solid var(--color-blue)' : '3px solid transparent',
              }}>
              <div className="flex items-center justify-between mb-1 gap-2">
                <span className="font-mono text-[10px]" style={{ color: 'var(--color-muted)' }}>{ticket.ticket_id}</span>
                <div className="flex items-center gap-1.5">
                  <SentimentIcon sentiment={ticket.sentiment} />
                  <AiQualityBadge quality={ticket.report_ai_quality} />
                  <span className="text-[9px] px-1.5 py-0.5 rounded font-bold border"
                        style={{
                          color: ticket.status === 'resolved' ? 'var(--color-green)' : 'var(--color-amber)',
                          borderColor: (ticket.status === 'resolved' ? 'var(--color-green)' : 'var(--color-amber)') + '40',
                          background: (ticket.status === 'resolved' ? 'var(--color-green)' : 'var(--color-amber)') + '15',
                        }}>
                    {ticket.status === 'resolved' ? '已结单' : '处理中'}
                  </span>
                </div>
              </div>
              <div className="flex items-center gap-2 text-[12px] mb-1">
                <span className="font-semibold">{ticket.user_id}</span>
                {ticket.category && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded font-medium"
                        style={{ background: 'rgba(20,184,166,0.12)', color: 'var(--color-green)' }}>
                    {ticket.category}
                  </span>
                )}
              </div>
              {ticket.summary && (
                <p className="text-[11px] truncate" style={{ color: 'var(--color-muted)' }}>{ticket.summary}</p>
              )}
              <div className="flex items-center gap-3 mt-1.5 text-[10px]" style={{ color: 'var(--color-muted)' }}>
                <span>创建：{fmtDate(ticket.created_at)}</span>
                {ticket.resolved_at && <span>结单：{fmtDate(ticket.resolved_at)}</span>}
              </div>
            </div>
          ))}
        </div>

        {/* Ticket detail */}
        <div className="flex-1 overflow-y-auto px-6 py-4">
          {!selectedTicket && !detailLoading && (
            <div className="flex flex-col items-center justify-center h-full gap-3 opacity-10">
              <ChevronRight size={32} />
              <span className="text-xs uppercase tracking-widest">点击左侧工单查看详情</span>
            </div>
          )}
          {detailLoading && (
            <div className="p-6 text-center text-[11px] italic" style={{ color: 'var(--color-muted)' }}>加载详情…</div>
          )}
          {selectedTicket && !detailLoading && (
            <div className="space-y-5 max-w-2xl">
              {/* Basic info */}
              <div>
                <div className="text-[10px] uppercase tracking-widest font-bold mb-2" style={{ color: 'var(--color-muted)' }}>工单信息</div>
                <div className="rounded-lg border p-4 text-[12px] space-y-2"
                     style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
                  <div className="flex justify-between">
                    <span style={{ color: 'var(--color-muted)' }}>工单号</span>
                    <span className="font-mono text-[10px]">{selectedTicket.ticket_id}</span>
                  </div>
                  <div className="flex justify-between">
                    <span style={{ color: 'var(--color-muted)' }}>客户 ID</span>
                    <span className="font-mono text-[10px]">{selectedTicket.user_id}</span>
                  </div>
                  <div className="flex justify-between">
                    <span style={{ color: 'var(--color-muted)' }}>状态</span>
                    <span>{selectedTicket.status === 'resolved' ? '已结单' : '处理中'}</span>
                  </div>
                  {selectedTicket.category && (
                    <div className="flex justify-between">
                      <span style={{ color: 'var(--color-muted)' }}>分类</span>
                      <span>{selectedTicket.category}</span>
                    </div>
                  )}
                  <div className="flex justify-between">
                    <span style={{ color: 'var(--color-muted)' }}>创建时间</span>
                    <span>{fmtDate(selectedTicket.created_at)}</span>
                  </div>
                  {selectedTicket.resolved_at && (
                    <div className="flex justify-between">
                      <span style={{ color: 'var(--color-muted)' }}>结单时间</span>
                      <span>{fmtDate(selectedTicket.resolved_at)}</span>
                    </div>
                  )}
                  {selectedTicket.report_resolution_type && (
                    <div className="flex justify-between">
                      <span style={{ color: 'var(--color-muted)' }}>结案类型</span>
                      <span>{selectedTicket.report_resolution_type}</span>
                    </div>
                  )}
                </div>
              </div>

              {/* Summary */}
              {selectedTicket.summary && (
                <div>
                  <div className="text-[10px] uppercase tracking-widest font-bold mb-2" style={{ color: 'var(--color-muted)' }}>问题摘要</div>
                  <div className="rounded-lg border p-4 text-[12px] leading-relaxed whitespace-pre-wrap"
                       style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
                    {selectedTicket.summary}
                  </div>
                </div>
              )}

              {/* Resolution */}
              {selectedTicket.resolution && (
                <div>
                  <div className="text-[10px] uppercase tracking-widest font-bold mb-2" style={{ color: 'var(--color-muted)' }}>结案方案</div>
                  <div className="rounded-lg border p-4 text-[12px] leading-relaxed whitespace-pre-wrap"
                       style={{ background: 'rgba(16,185,129,0.06)', borderColor: 'rgba(16,185,129,0.25)' }}>
                    {selectedTicket.resolution}
                  </div>
                </div>
              )}

              {/* Key issues */}
              {selectedTicket.report_key_issues && selectedTicket.report_key_issues.length > 0 && (
                <div>
                  <div className="text-[10px] uppercase tracking-widest font-bold mb-2" style={{ color: 'var(--color-muted)' }}>关键问题</div>
                  <ul className="space-y-1.5">
                    {selectedTicket.report_key_issues.map((issue, i) => (
                      <li key={i} className="flex items-start gap-2 text-[12px]">
                        <AlertCircle size={11} className="mt-0.5 shrink-0" style={{ color: 'var(--color-amber)' }} />
                        <span>{issue}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Conversation history */}
              <div>
                <div className="text-[10px] uppercase tracking-widest font-bold mb-2" style={{ color: 'var(--color-muted)' }}>完整对话记录</div>
                {msgLoading && (
                  <div className="text-[11px] italic" style={{ color: 'var(--color-muted)' }}>加载对话…</div>
                )}
                {!msgLoading && messages.length === 0 && (
                  <div className="text-[11px] italic" style={{ color: 'var(--color-muted)', opacity: 0.5 }}>无对话记录</div>
                )}
                <div className="space-y-3">
                  {messages.map((msg, i) => {
                    if (msg.role === 'system') return (
                      <div key={i} className="flex items-center justify-center">
                        <span className="text-[10px] px-2.5 py-0.5 rounded-full border italic"
                              style={{ color: 'var(--color-muted)', borderColor: 'var(--color-border)', background: 'var(--color-surface-2)', opacity: 0.7 }}>
                          {msg.content}
                        </span>
                      </div>
                    );
                    return (
                      <div key={i} className={`flex ${msg.role === 'agent' ? 'justify-end' : 'justify-start'}`}>
                        <div className={`max-w-[78%] flex flex-col ${msg.role === 'agent' ? 'items-end' : 'items-start'}`}>
                          <div className={`text-[9px] uppercase tracking-widest mb-1 font-bold px-1 font-mono ${msg.role === 'agent' ? 'text-right' : ''}`}
                               style={{ color: roleColor(msg.role) }}>
                            {roleLabel(msg.role)}
                            {msg.node_name && <span className="ml-1 normal-case font-normal opacity-60">({msg.node_name})</span>}
                            {' · '}{fmtDate(msg.created_at)}
                          </div>
                          <div className="px-3 py-2 text-[12px] leading-relaxed"
                               style={{
                                 background: roleBg(msg.role),
                                 color: msg.role === 'agent' ? '#fff' : 'var(--color-text)',
                                 borderRadius: msg.role === 'agent' ? '18px 18px 4px 18px' : '18px 18px 18px 4px',
                               }}>
                            <MsgContent content={msg.content} />
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </motion.div>
  );
}

// ─── AnalyticsPanel ───────────────────────────────────────────────────────────

function MetricCard({ label, value, sub, color }: { label: string; value: string | number; sub?: string; color?: string }) {
  return (
    <div className="rounded-xl border p-4 flex flex-col gap-1"
         style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
      <div className="text-[10px] uppercase tracking-widest font-bold" style={{ color: 'var(--color-muted)' }}>{label}</div>
      <div className="text-2xl font-bold" style={{ color: color ?? 'var(--color-text)' }}>{value}</div>
      {sub && <div className="text-[11px]" style={{ color: 'var(--color-muted)' }}>{sub}</div>}
    </div>
  );
}

function RateBar({ label, rate, color }: { label: string; rate: number; color: string }) {
  const pct = Math.round(rate * 100);
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-[12px]">
        <span>{label}</span>
        <span className="font-bold font-mono" style={{ color }}>{pct}%</span>
      </div>
      <div className="h-2 rounded-full overflow-hidden" style={{ background: 'var(--color-surface-2)' }}>
        <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, background: color }} />
      </div>
    </div>
  );
}

function AnalyticsPanel({ onClose }: { onClose: () => void }) {
  const [days, setDays]               = useState(7);
  const [analytics, setAnalytics]     = useState<AnalyticsData | null>(null);
  const [todayMetrics, setTodayMetrics] = useState<TodayMetrics | null>(null);
  const [loading, setLoading]         = useState(false);

  const fetchData = useCallback(async (d: number) => {
    setLoading(true);
    try {
      const [aRes, tRes] = await Promise.all([
        fetch(`${BASE_URL}/api/workspace/analytics?days=${d}`),
        fetch(`${BASE_URL}/api/workspace/metrics/today`),
      ]);
      if (aRes.ok) setAnalytics(await aRes.json());
      if (tRes.ok) setTodayMetrics(await tRes.json());
    } catch { /* ignore */ }
    setLoading(false);
  }, []);

  useEffect(() => { fetchData(days); }, [fetchData, days]);

  const maxIntent = analytics?.top_intents?.[0]?.count ?? 1;

  const INTENT_LABELS: Record<string, string> = {
    product_node:    '商品推荐',  product:    '商品推荐',
    faq_node:        'FAQ 咨询',  faq:        'FAQ 咨询',
    order_read_node: '订单查询',  order_read: '订单查询',
    order_write_node:'订单操作',  order_write:'订单操作',
    aftersales_node: '售后处理',  aftersales: '售后处理',
    general_node:    '通用对话',  general:    '通用对话',
    unknown:         '未知节点',
    transfer_to_human: '转人工',
  };

  const aiResolveRate = analytics && analytics.total_sessions > 0
    ? analytics.ai_resolved / analytics.total_sessions : 0;
  const resolveRate = analytics && analytics.total_sessions > 0
    ? analytics.resolved_count / analytics.total_sessions : 0;
  const hitlApprovalRate = todayMetrics && (todayMetrics.hitl_approvals + todayMetrics.hitl_rejections) > 0
    ? todayMetrics.hitl_approvals / (todayMetrics.hitl_approvals + todayMetrics.hitl_rejections) : 0;

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-40 flex flex-col"
      style={{ background: 'var(--color-bg)', color: 'var(--color-text)' }}>

      {/* Panel header */}
      <div className="h-14 border-b flex items-center gap-3 px-6 shrink-0"
           style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
        <BarChart3 size={16} style={{ color: 'var(--color-blue)' }} />
        <span className="font-semibold">运营数据大盘</span>
        <div className="flex-1" />
        <select
          value={days}
          onChange={e => setDays(Number(e.target.value))}
          className="rounded-lg border px-2 py-1 text-[12px] outline-none mr-2"
          style={{ background: 'var(--color-surface-2)', borderColor: 'var(--color-border)', color: 'var(--color-text)' }}>
          <option value={7}>近 7 天</option>
          <option value={30}>近 30 天</option>
        </select>
        <button onClick={onClose}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-[11px] font-bold transition-all"
          style={{ borderColor: 'var(--color-border)', color: 'var(--color-muted)', background: 'var(--color-bg)' }}>
          <X size={11} /> 关闭
        </button>
      </div>

      {/* Scrollable body */}
      <div className="flex-1 overflow-y-auto px-6 py-5">
        {loading && (
          <div className="text-center text-[11px] italic py-10" style={{ color: 'var(--color-muted)' }}>加载数据…</div>
        )}

        {/* Daily volume sparkline */}
        {!loading && analytics?.daily_volume && analytics.daily_volume.length > 0 && (
          <section className="mb-6">
            <div className="text-[10px] uppercase tracking-widest font-bold mb-3" style={{ color: 'var(--color-muted)' }}>
              每日会话量（近 {analytics.period_days} 天）
            </div>
            <div
              className="rounded-xl border p-4"
              style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
            >
              {(() => {
                const data = analytics.daily_volume!;
                const maxVol = Math.max(...data.map(d => d.count), 1);
                return (
                  <div className="flex items-end gap-1 h-20">
                    {data.map((d, i) => {
                      const heightPct = Math.max((d.count / maxVol) * 100, 4);
                      const label = d.date.slice(5); // "MM-DD"
                      return (
                        <div
                          key={i}
                          className="flex-1 flex flex-col items-center gap-1 group"
                          title={`${d.date}: ${d.count} 会话`}
                        >
                          <span
                            className="text-[9px] font-bold opacity-0 group-hover:opacity-100 transition-opacity"
                            style={{ color: 'var(--color-blue)' }}
                          >
                            {d.count}
                          </span>
                          <div className="w-full flex items-end" style={{ height: 56 }}>
                            <div
                              className="w-full rounded-t transition-all"
                              style={{
                                height: `${heightPct}%`,
                                background: d.count > 0
                                  ? 'linear-gradient(to top, rgba(59,130,246,0.7), rgba(99,102,241,0.4))'
                                  : 'rgba(99,102,241,0.1)',
                              }}
                            />
                          </div>
                          <span className="text-[8px] font-mono" style={{ color: 'var(--color-muted)', opacity: 0.6 }}>
                            {label}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                );
              })()}
            </div>
          </section>
        )}

        {/* M3: AI resolution rate highlight */}
        {!loading && analytics && analytics.total_sessions > 0 && (
          <section className="mb-6">
            <div className="rounded-xl border p-5 flex items-center gap-5"
                 style={{ background: 'rgba(16,185,129,0.06)', borderColor: 'rgba(16,185,129,0.3)' }}>
              <div>
                <div className="text-[10px] uppercase tracking-widest font-bold mb-1" style={{ color: 'var(--color-muted)' }}>AI自主解决率</div>
                <div className="text-4xl font-bold" style={{ color: 'var(--color-green)' }}>
                  {Math.round(analytics.ai_resolved / analytics.total_sessions * 100)}%
                </div>
              </div>
              <div className="text-[12px] leading-relaxed" style={{ color: 'var(--color-muted)' }}>
                近 {analytics.period_days} 天内，共 <span style={{ color: 'var(--color-text)' }}>{analytics.total_sessions}</span> 个会话中，
                <span style={{ color: 'var(--color-green)' }}> {analytics.ai_resolved} </span>
                个由 AI 独立解决，无需人工介入。
              </div>
            </div>
          </section>
        )}

        {!loading && todayMetrics && (
          <section className="mb-6">
            <div className="text-[10px] uppercase tracking-widest font-bold mb-3" style={{ color: 'var(--color-muted)' }}>今日 KPI（{todayMetrics.date}）</div>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
              <MetricCard label="总会话" value={todayMetrics.total_sessions} color="var(--color-blue)" />
              <MetricCard label="AI 解决" value={todayMetrics.ai_resolved} color="var(--color-green)" />
              <MetricCard label="转人工" value={todayMetrics.escalated_to_human} color="var(--color-amber)" />
              <MetricCard label="HITL 审批" value={`${todayMetrics.hitl_approvals}✓ / ${todayMetrics.hitl_rejections}✗`} color="var(--color-pink)" />
              <MetricCard
                label="平均响应"
                value={todayMetrics.avg_first_response_ms >= 1000
                  ? `${(todayMetrics.avg_first_response_ms / 1000).toFixed(1)}s`
                  : `${todayMetrics.avg_first_response_ms}ms`}
                color="var(--color-text)"
              />
            </div>
          </section>
        )}

        {!loading && analytics && (
          <>
            <section className="mb-6">
              <div className="text-[10px] uppercase tracking-widest font-bold mb-3" style={{ color: 'var(--color-muted)' }}>
                趋势概览（近 {analytics.period_days} 天 · 共 {analytics.total_sessions} 会话）
              </div>
              <div className="rounded-xl border p-5 space-y-4"
                   style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
                <RateBar label="AI 解决率" rate={aiResolveRate} color="var(--color-green)" />
                <RateBar label="结单率" rate={resolveRate} color="var(--color-blue)" />
                <RateBar label="HITL 通过率（今日）" rate={hitlApprovalRate} color="var(--color-amber)" />
              </div>
            </section>

            {analytics.top_intents && analytics.top_intents.length > 0 && (
              <section className="mb-6">
                <div className="text-[10px] uppercase tracking-widest font-bold mb-3" style={{ color: 'var(--color-muted)' }}>意图分布</div>
                <div className="rounded-xl border p-5 space-y-3"
                     style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
                  {analytics.top_intents.map((item, i) => (
                    <div key={i} className="space-y-1">
                      <div className="flex justify-between text-[12px]">
                        <span>
                          {INTENT_LABELS[item.intent] ?? item.intent}
                          <code className="ml-1.5 text-[9px] opacity-40 font-mono">{item.intent}</code>
                        </span>
                        <span className="font-bold font-mono" style={{ color: 'var(--color-blue)' }}>{item.count}</span>
                      </div>
                      <div className="h-2 rounded-full overflow-hidden" style={{ background: 'var(--color-surface-2)' }}>
                        <div
                          className="h-full rounded-full transition-all"
                          style={{ width: `${Math.round((item.count / maxIntent) * 100)}%`, background: 'var(--color-blue)' }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {/* Escalation by node */}
            {analytics.escalation_by_node && analytics.escalation_by_node.length > 0 && (
              <section className="mb-6">
                <div className="text-[10px] uppercase tracking-widest font-bold mb-3" style={{ color: 'var(--color-muted)' }}>
                  转人工节点分布
                  <span className="ml-2 normal-case font-normal" style={{ color: 'var(--color-muted)', opacity: 0.6 }}>
                    — 哪个节点触发了最多人工接管
                  </span>
                </div>
                <div className="rounded-xl border p-5 space-y-3"
                     style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
                  {(() => {
                    const maxEsc = Math.max(...analytics.escalation_by_node.map(e => e.count), 1);
                    const nodeColors: Record<string, string> = {
                      product_node:    '#3B82F6', product:    '#3B82F6',
                      faq_node:        '#06B6D4', faq:        '#06B6D4',
                      order_read_node: '#10B981', order_read: '#10B981',
                      order_write_node:'#F59E0B', order_write:'#F59E0B',
                      aftersales_node: '#F97316', aftersales: '#F97316',
                      general_node:    '#64748B', general:    '#64748B',
                      unknown:         '#6366F1',
                      transfer_to_human: '#EC4899',
                    };
                    return analytics.escalation_by_node.map((item, i) => {
                      const barColor = nodeColors[item.node] ?? '#8B5CF6';
                      return (
                        <div key={i} className="space-y-1">
                          <div className="flex justify-between text-[12px]">
                            <span>{INTENT_LABELS[item.node] ?? item.node}</span>
                            <span className="font-bold font-mono" style={{ color: barColor }}>{item.count}</span>
                          </div>
                          <div className="h-2 rounded-full overflow-hidden" style={{ background: 'var(--color-surface-2)' }}>
                            <div
                              className="h-full rounded-full transition-all"
                              style={{ width: `${Math.round((item.count / maxEsc) * 100)}%`, background: barColor }}
                            />
                          </div>
                        </div>
                      );
                    });
                  })()}
                </div>
              </section>
            )}

            {/* M3: Category distribution */}
            <section className="mb-6">
              <div className="text-[10px] uppercase tracking-widest font-bold mb-3" style={{ color: 'var(--color-muted)' }}>分类分布</div>
              {analytics.category_distribution && analytics.category_distribution.length > 0 ? (
                <div className="rounded-xl border p-5 space-y-3"
                     style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
                  {(() => {
                    const maxCat = Math.max(...analytics.category_distribution!.map(c => c.count), 1);
                    return analytics.category_distribution!.map((item, i) => (
                      <div key={i} className="space-y-1">
                        <div className="flex justify-between text-[12px]">
                          <span>{item.category}</span>
                          <span className="font-bold font-mono" style={{ color: 'var(--color-green)' }}>{item.count}</span>
                        </div>
                        <div className="h-2 rounded-full overflow-hidden" style={{ background: 'var(--color-surface-2)' }}>
                          <div
                            className="h-full rounded-full transition-all"
                            style={{ width: `${Math.round((item.count / maxCat) * 100)}%`, background: 'rgba(20,184,166,0.7)' }}
                          />
                        </div>
                      </div>
                    ));
                  })()}
                </div>
              ) : (
                <div className="rounded-xl border p-4 text-[12px] text-center italic"
                     style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)', color: 'var(--color-muted)' }}>
                  （分类数据将在工单结案后生成）
                </div>
              )}
            </section>

            <section>
              <div className="text-[10px] uppercase tracking-widest font-bold mb-3" style={{ color: 'var(--color-muted)' }}>其他指标</div>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                <MetricCard label="升级人工" value={analytics.escalated_to_human} color="var(--color-amber)" />
                <MetricCard label="HITL 次数" value={analytics.hitl_count} color="var(--color-pink)" />
                <MetricCard
                  label="平均 AI 响应"
                  value={analytics.avg_bot_response_ms > 0
                    ? analytics.avg_bot_response_ms >= 1000
                      ? `${(analytics.avg_bot_response_ms / 1000).toFixed(1)}s`
                      : `${analytics.avg_bot_response_ms}ms`
                    : '—'}
                  color="var(--color-text)"
                />
                <MetricCard label="已结单" value={analytics.resolved_count} color="var(--color-green)" />
                <MetricCard label="处理中" value={analytics.open_count} color="var(--color-rose)" />
                <MetricCard
                  label="平均解决时长"
                  value={analytics.avg_resolution_minutes != null
                    ? analytics.avg_resolution_minutes >= 60
                      ? `${(analytics.avg_resolution_minutes / 60).toFixed(1)}h`
                      : `${Math.round(analytics.avg_resolution_minutes)}min`
                    : '—'}
                  color="var(--color-text)"
                />
                {analytics.csat && analytics.csat.count > 0 && (
                  <MetricCard
                    label={`CSAT 评分 (${analytics.csat.count})`}
                    value={analytics.csat.avg_rating != null ? `${analytics.csat.avg_rating.toFixed(1)} ★` : '—'}
                    color="#f59e0b"
                  />
                )}
              </div>
            </section>
          </>
        )}
      </div>
    </motion.div>
  );
}

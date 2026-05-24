import { useState, useEffect, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { Send, Bot, User, Headset, Loader2, WifiOff, Star, LogOut, Clock, ChevronLeft, Plus, MessageSquare, ImagePlus, X } from 'lucide-react';
import socket from '../lib/socket';
import { ChatMsg } from '../types';
import type { Identity } from '../lib/auth';
import { clearToken, resetIdentityCache } from '../lib/auth';
import { listMySessions, type SessionSummary } from '../lib/customerApi';

const API_BASE = 'http://localhost:8000';

/** Parse [ACTION:label:text] markers from bot reply content.
 * Returns cleaned content (markers removed) and an array of action buttons. */
function parseActionButtons(content: string): { clean: string; actions: Array<{ label: string; text: string }> } {
  const actions: Array<{ label: string; text: string }> = [];
  const clean = content.replace(/\[ACTION:([^:]+):([^\]]+)\]/g, (_, label, text) => {
    actions.push({ label: label.trim(), text: text.trim() });
    return '';
  }).trim();
  return { clean, actions };
}

/** Split message content into text/image segments for rendering. */
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

function MessageContent({ content }: { content: string }) {
  const parts = parseContent(content);
  return (
    <>
      {parts.map((p, i) =>
        p.type === 'image' ? (
          <img key={i} src={p.value.startsWith('/') ? `${API_BASE}${p.value}` : p.value}
               alt="图片附件"
               className="max-w-full rounded-xl mt-1 block"
               style={{ maxHeight: 260, objectFit: 'contain', border: '1px solid rgba(255,255,255,0.08)' }} />
        ) : (
          <span key={i} style={{ whiteSpace: 'pre-wrap' }}>{p.value}</span>
        )
      )}
    </>
  );
}

type ConnState = 'disconnected' | 'connected';

const WELCOME: ChatMsg = {
  role: 'bot',
  content: '您好！欢迎来到缘梦婚纱 💐\n请问有什么可以帮助您的吗？\n\n您可以询问：婚纱款式 · 定制流程 · 尺码量体 · 订单查询 · 加急服务',
  timestamp: new Date().toISOString(),
};

interface Props {
  identity: Identity;
  sessionId: string | null;
  onSessionChange: (id: string) => void;
}

export default function CustomerPortal({ identity, sessionId, onSessionChange }: Props) {
  const { userId: guestId, displayName, isGuest } = identity;
  const [messages, setMessages] = useState<ChatMsg[]>([WELCOME]);
  const [input, setInput] = useState('');
  const [conn, setConn] = useState<ConnState>(socket.connected ? 'connected' : 'disconnected');
  const [agentMode, setAgentMode] = useState(false);
  const [loading, setLoading] = useState(false);
  const [progressText, setProgressText] = useState<string>('');  // F1: real-time tool progress hint
  // D: Typing indicators
  const [botTyping, setBotTyping] = useState(false);
  const [agentTyping, setAgentTyping] = useState(false);
  const typingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const customerTypingRef = useRef(false);
  // E: CSAT
  const [ratingSessionId, setRatingSessionId] = useState<string | null>(null);
  const [ratingSubmitted, setRatingSubmitted] = useState(false);
  // F: History view
  const [historyView, setHistoryView] = useState(false);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  // G: Image upload
  const [uploading, setUploading] = useState(false);
  const [imagePreview, setImagePreview] = useState<{ file: File; dataUrl: string } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  // Local copy of sessionId so we can pass it to join on reconnect
  const sessionIdRef = useRef<string | null>(sessionId);
  useEffect(() => { sessionIdRef.current = sessionId; }, [sessionId]);

  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const joinedRef = useRef(false); // guard against double-join on StrictMode / reconnect

  // ── join / rejoin ────────────────────────────────────────────────────────────
  const doJoin = useCallback(() => {
    if (joinedRef.current) return;
    joinedRef.current = true;

    // user_id is authoritative from JWT on the server; we still send it as a
    // fallback for open/guest mode where no token is present.
    const payload: { user_id: string; session_id?: string } = { user_id: guestId };
    if (sessionIdRef.current) payload.session_id = sessionIdRef.current;

    socket.emit('join', payload, (res: {
      session_id: string;
      thread_id: string;
      mode: string;
      history: ChatMsg[];
      user_id?: string;
      display_name?: string;
    }) => {
      onSessionChange(res.session_id);
      setConn('connected');
      // Restore conversation history when rejoining an existing session.
      // Filter out internal system messages — customers never see those.
      if (res.history && res.history.length > 0) {
        setMessages(res.history.filter((m: ChatMsg) => m.role !== 'system'));
        setAgentMode(res.mode === 'human');
      }
    });
  }, [guestId, onSessionChange]);

  const openHistory = useCallback(async () => {
    setHistoryView(true);
    setSessionsLoading(true);
    try {
      const data = await listMySessions();
      setSessions(data);
    } catch {
      setSessions([]);
    } finally {
      setSessionsLoading(false);
    }
  }, []);

  const restoreSession = useCallback((sid: string) => {
    joinedRef.current = false;
    setMessages([WELCOME]);
    setHistoryView(false);
    // Temporarily set the session ref so doJoin sends it
    sessionIdRef.current = sid;
    onSessionChange(sid);
    if (socket.connected) {
      joinedRef.current = false;
      const payload = { user_id: guestId, session_id: sid };
      socket.emit('join', payload, (res: {
        session_id: string; thread_id: string; mode: string; history: ChatMsg[];
      }) => {
        onSessionChange(res.session_id);
        if (res.history && res.history.length > 0) {
          setMessages(res.history.filter((m: ChatMsg) => m.role !== 'system'));
          setAgentMode(res.mode === 'human');
        }
      });
      joinedRef.current = true;
    }
  }, [guestId, onSessionChange]);

  const startNewSession = useCallback(() => {
    joinedRef.current = false;
    sessionIdRef.current = null;
    onSessionChange('');
    setMessages([WELCOME]);
    setHistoryView(false);
    setAgentMode(false);
    if (socket.connected) {
      const payload = { user_id: guestId };
      socket.emit('join', payload, (res: {
        session_id: string; thread_id: string; mode: string; history: ChatMsg[];
      }) => {
        onSessionChange(res.session_id);
      });
      joinedRef.current = true;
    }
  }, [guestId, onSessionChange]);

  useEffect(() => {
    if (socket.connected) doJoin();

    const onConnect = () => { setConn('connected'); joinedRef.current = false; doJoin(); };
    const onDisconnect = () => { setConn('disconnected'); };

    socket.on('connect', onConnect);
    socket.on('disconnect', onDisconnect);

    socket.on('bot_reply', (msg: ChatMsg) => {
      setMessages(prev => {
        // Deduplicate: skip if a message with same role+content+timestamp already exists
        const isDup = prev.some(
          m => m.role === msg.role && m.content === msg.content && m.timestamp === msg.timestamp
        );
        return isDup ? prev : [...prev, msg];
      });
      setLoading(false);
      setProgressText('');     // F1: clear progress hint when reply arrives
      setBotTyping(false);     // D: hide typing indicator on reply
      setAgentTyping(false);
      if (msg.role === 'agent') setAgentMode(true);
    });

    // F1: Tool progress events — update loading bubble text in real-time
    socket.on('bot_progress', (data: { stage: string; text: string }) => {
      setProgressText(data.text);
    });

    // D: Typing indicators from server
    socket.on('bot_typing', (data: { typing: boolean }) => {
      setBotTyping(data.typing);
    });
    socket.on('agent_typing', (data: { typing: boolean }) => {
      setAgentTyping(data.typing);
      // Auto-clear after 4s if no further events
      if (data.typing) {
        setTimeout(() => setAgentTyping(false), 4000);
      }
    });

    // E: CSAT rating request
    socket.on('request_rating', (data: { session_id: string }) => {
      setRatingSessionId(data.session_id);
      setRatingSubmitted(false);
    });

    return () => {
      socket.off('connect', onConnect);
      socket.off('disconnect', onDisconnect);
      socket.off('bot_reply');
      socket.off('bot_progress');
      socket.off('bot_typing');
      socket.off('agent_typing');
      socket.off('request_rating');
    };
  }, [doJoin]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  // ── send ─────────────────────────────────────────────────────────────────────
  const send = useCallback((text?: string) => {
    const content = (text ?? input).trim();
    if (!content) return;

    const userMsg: ChatMsg = { role: 'user', content, timestamp: new Date().toISOString() };
    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setLoading(true);

    if (!sessionId || !socket.connected) {
      setTimeout(() => {
        const errMsg: ChatMsg = {
          role: 'bot',
          content: '⚠️ 当前未连接到服务器，请确认后端已启动并刷新页面。',
          timestamp: new Date().toISOString(),
        };
        setMessages(prev => [...prev, errMsg]);
        setLoading(false);
      }, 800);
      return;
    }

    socket.emit('user_message', { session_id: sessionId, content });
    inputRef.current?.focus();
  }, [input, sessionId]);

  // D: Emit customer typing indicator (debounced stop after 2s idle)
  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setInput(e.target.value);
    if (!sessionId || !socket.connected) return;
    if (!customerTypingRef.current) {
      customerTypingRef.current = true;
      socket.emit('customer_typing', { session_id: sessionId, typing: true });
    }
    if (typingTimerRef.current) clearTimeout(typingTimerRef.current);
    typingTimerRef.current = setTimeout(() => {
      customerTypingRef.current = false;
      socket.emit('customer_typing', { session_id: sessionId, typing: false });
    }, 2000);
  };

  // E: Submit CSAT rating
  const submitRating = (rating: number) => {
    if (!ratingSessionId) return;
    socket.emit('submit_rating', { session_id: ratingSessionId, rating }, () => {});
    setRatingSubmitted(true);
    // Auto-dismiss after 3s
    setTimeout(() => setRatingSessionId(null), 3000);
  };

  // G: Image select → preview
  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    // Reset so same file can be picked again
    e.target.value = '';
    const reader = new FileReader();
    reader.onload = ev => {
      setImagePreview({ file, dataUrl: ev.target?.result as string });
    };
    reader.readAsDataURL(file);
  };

  // G: Upload image and send as message
  const sendImage = useCallback(async () => {
    if (!imagePreview || uploading) return;
    setUploading(true);
    try {
      const token = localStorage.getItem('ym_token') || '';
      const form = new FormData();
      form.append('file', imagePreview.file);
      const res = await fetch(`${API_BASE}/api/upload`, {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: form,
      });
      if (!res.ok) throw new Error('Upload failed');
      const { url } = await res.json() as { url: string };
      // Build message: optional caption text + image marker
      const caption = input.trim();
      const content = caption ? `${caption}\n[IMAGE:${url}]` : `[IMAGE:${url}]`;
      setImagePreview(null);
      setInput('');
      // Send as normal message
      const userMsg: ChatMsg = { role: 'user', content, timestamp: new Date().toISOString() };
      setMessages(prev => [...prev, userMsg]);
      setLoading(true);
      if (sessionId && socket.connected) {
        socket.emit('user_message', { session_id: sessionId, content });
      }
    } catch (err) {
      console.error('Image upload failed:', err);
    } finally {
      setUploading(false);
    }
  }, [imagePreview, uploading, input, sessionId]);

  const isConnected = conn === 'connected' && !!sessionId;

  const QUICK = ['了解定制流程', '查询我的订单', '申请加急制作', '退换货政策'];

  return (
    <div className="relative flex flex-col h-full" style={{ background: 'var(--color-surface)', color: 'var(--color-text)' }}>

      {/* Header */}
      <div className="p-4 border-b flex items-center gap-3 shrink-0"
           style={{ background: 'var(--color-surface-2)', borderColor: 'var(--color-border)' }}>
        <div className="w-9 h-9 rounded-xl flex items-center justify-center text-lg shadow-lg shrink-0"
             style={{ background: 'var(--color-pink)', boxShadow: '0 0 14px var(--color-pink-glow)' }}>
          💐
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="font-semibold text-sm truncate flex items-center gap-1.5">
            缘梦婚纱 <span className="opacity-40 font-light">客服</span>
          </h3>
          <div className="flex items-center gap-1.5 mt-0.5">
            <span className="w-1.5 h-1.5 rounded-full shrink-0 transition-colors"
                  style={{
                    background: isConnected ? 'var(--color-green)' : 'var(--color-muted)',
                    boxShadow: isConnected ? '0 0 5px var(--color-green)' : 'none',
                  }} />
            <span className="text-[10px] uppercase tracking-widest font-bold truncate"
                  style={{ color: 'var(--color-muted)' }}>
              {isConnected ? (agentMode ? '客服接待中' : '在线客服') : '连接中…'}
            </span>
            {/* Customer ID badge */}
            <span className="text-[10px] px-1.5 py-0.5 rounded font-mono truncate max-w-[120px]"
                  style={{ background: 'rgba(99,102,241,0.1)', color: 'var(--color-blue)', border: '1px solid rgba(99,102,241,0.18)' }}
                  title={guestId}>
              {displayName || guestId}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {agentMode && !historyView && (
            <div className="flex items-center gap-1 text-[10px] px-2 py-1 rounded border font-bold"
                 style={{ color: 'var(--color-green)', borderColor: 'rgba(16,185,129,0.3)', background: 'rgba(16,185,129,0.08)' }}>
              <Headset size={10} /> 人工
            </div>
          )}
          {/* History — only shown for authenticated (non-guest) users */}
          {!isGuest && !historyView && (
            <button
              onClick={openHistory}
              title="历史对话"
              className="flex items-center gap-1 text-[10px] px-2 py-1 rounded border font-bold transition-all"
              style={{ color: 'var(--color-muted)', borderColor: 'var(--color-border)', background: 'var(--color-surface)', cursor: 'pointer' }}>
              <Clock size={10} />
            </button>
          )}
          {historyView && (
            <button
              onClick={() => setHistoryView(false)}
              title="返回对话"
              className="flex items-center gap-1 text-[10px] px-2 py-1 rounded border font-bold transition-all"
              style={{ color: 'var(--color-blue)', borderColor: 'rgba(59,130,246,0.3)', background: 'rgba(59,130,246,0.06)', cursor: 'pointer' }}>
              <ChevronLeft size={10} /> 返回
            </button>
          )}
          {/* Logout — only shown for authenticated (non-guest) users */}
          {!isGuest && (
            <button
              onClick={() => { clearToken(); resetIdentityCache(); window.location.reload(); }}
              title="退出登录"
              className="flex items-center gap-1 text-[10px] px-2 py-1 rounded border font-bold transition-all"
              style={{ color: 'var(--color-muted)', borderColor: 'var(--color-border)', background: 'var(--color-surface)', cursor: 'pointer' }}>
              <LogOut size={10} />
            </button>
          )}
        </div>
      </div>

      {/* Offline banner */}
      {!isConnected && (
        <div className="flex items-center gap-2 px-4 py-2 text-[11px] shrink-0"
             style={{ background: 'rgba(100,116,139,0.12)', color: 'var(--color-muted)', borderBottom: '1px solid var(--color-border)' }}>
          <WifiOff size={11} />
          未连接服务器 — 仍可输入，发送后显示离线提示
        </div>
      )}

      {/* History view */}
      {historyView && (
        <div className="flex-1 overflow-y-auto px-4 py-4 flex flex-col gap-3">
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs font-semibold" style={{ color: 'var(--color-text)' }}>历史对话记录</span>
            <button
              onClick={startNewSession}
              className="flex items-center gap-1 text-[11px] px-2.5 py-1.5 rounded-lg font-medium transition-all"
              style={{ background: 'var(--color-pink)', color: '#fff', cursor: 'pointer', boxShadow: '0 0 10px var(--color-pink-glow)' }}>
              <Plus size={11} /> 新建对话
            </button>
          </div>

          {sessionsLoading && (
            <div className="flex items-center justify-center py-8 gap-2" style={{ color: 'var(--color-muted)' }}>
              <Loader2 size={14} className="animate-spin" />
              <span className="text-xs">加载中…</span>
            </div>
          )}

          {!sessionsLoading && sessions.length === 0 && (
            <div className="flex flex-col items-center justify-center py-12 gap-2 opacity-40">
              <MessageSquare size={28} style={{ color: 'var(--color-muted)' }} />
              <p className="text-xs text-center" style={{ color: 'var(--color-muted)' }}>暂无历史对话</p>
            </div>
          )}

          {!sessionsLoading && sessions.map(s => {
            const date = s.updated_at ? new Date(s.updated_at) : null;
            const dateStr = date
              ? date.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' }) + ' ' +
                date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
              : '';
            const isActive = s.mode !== 'resolved' && s.mode !== 'closed';
            const isCurrent = s.session_id === sessionId;
            return (
              <button
                key={s.session_id}
                onClick={() => restoreSession(s.session_id)}
                className="w-full text-left rounded-xl border p-3 transition-all"
                style={{
                  background: isCurrent ? 'rgba(236,72,153,0.06)' : 'var(--color-surface-2)',
                  borderColor: isCurrent ? 'rgba(236,72,153,0.3)' : 'var(--color-border)',
                  cursor: 'pointer',
                }}>
                <div className="flex items-start justify-between gap-2 mb-1">
                  <span className="text-[11px] font-mono truncate" style={{ color: 'var(--color-muted)' }}>
                    {s.session_id.slice(0, 8)}…
                  </span>
                  <div className="flex items-center gap-1.5 shrink-0">
                    {isActive && (
                      <span className="w-1.5 h-1.5 rounded-full" style={{ background: 'var(--color-green)', boxShadow: '0 0 4px var(--color-green)' }} />
                    )}
                    <span className="text-[10px]" style={{ color: 'var(--color-muted)' }}>{dateStr}</span>
                  </div>
                </div>
                <p className="text-[12px] leading-relaxed line-clamp-2" style={{ color: 'var(--color-text)' }}>
                  {s.last_content || s.first_content || '（空会话）'}
                </p>
                <div className="flex items-center gap-2 mt-1.5">
                  <span className="text-[10px]" style={{ color: 'var(--color-muted)' }}>{s.msg_count} 条消息</span>
                  {isCurrent && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded"
                          style={{ background: 'rgba(236,72,153,0.12)', color: 'var(--color-pink)' }}>
                      当前
                    </span>
                  )}
                </div>
              </button>
            );
          })}
        </div>
      )}

      {/* Messages */}
      {!historyView && <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        <AnimatePresence initial={false}>
          {messages.map((msg, i) => (
            <motion.div key={i}
              initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.15 }}
              className={`flex gap-2 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>

              {msg.role !== 'user' && (
                <div className="w-7 h-7 rounded-lg shrink-0 flex items-center justify-center mt-0.5"
                     style={{ background: 'var(--color-surface-2)', border: '1px solid var(--color-border)' }}>
                  {msg.role === 'agent'
                    ? <Headset size={12} style={{ color: 'var(--color-green)' }} />
                    : <Bot size={12} style={{ color: 'var(--color-pink)' }} />}
                </div>
              )}

              <div className="max-w-[80%]">
                <div className="text-[9px] uppercase tracking-widest mb-1 px-1 font-bold"
                     style={{ color: roleColor(msg.role) }}>
                  {roleLabel(msg.role)}
                </div>
                {/* F2: Parse [ACTION] markers from bot messages */}
                {(() => {
                  const isBotMsg = msg.role === 'bot' || msg.role === 'agent';
                  const { clean, actions } = isBotMsg ? parseActionButtons(msg.content) : { clean: msg.content, actions: [] };
                  return (
                    <>
                      <div className="px-3.5 py-2.5 text-[13px] leading-relaxed prose-bubble"
                           style={{
                             background: msg.role === 'user' ? 'var(--color-blue)' : 'var(--color-surface-2)',
                             color: msg.role === 'user' ? '#fff' : 'var(--color-text)',
                             border: `1px solid ${msg.role === 'user' ? 'transparent' : 'var(--color-border)'}`,
                             borderRadius: msg.role === 'user' ? '18px 18px 4px 18px' : '18px 18px 18px 4px',
                           }}>
                        <MessageContent content={clean} />
                      </div>
                      {actions.length > 0 && (
                        <div className="flex flex-wrap gap-1.5 mt-1.5 px-1">
                          {actions.map((a, ai) => (
                            <motion.button key={ai}
                              onClick={() => send(a.text)}
                              whileHover={{ scale: 1.04 }}
                              whileTap={{ scale: 0.96 }}
                              className="text-[11px] px-3 py-1 rounded-full border font-medium"
                              style={{
                                borderColor: 'var(--color-pink)',
                                color: 'var(--color-pink)',
                                background: 'rgba(236,72,153,0.08)',
                                cursor: 'pointer',
                              }}>
                              {a.label}
                            </motion.button>
                          ))}
                        </div>
                      )}
                    </>
                  );
                })()}
              </div>

              {msg.role === 'user' && (
                <div className="w-7 h-7 rounded-lg shrink-0 flex items-center justify-center mt-0.5"
                     style={{ background: 'rgba(59,130,246,0.12)', border: '1px solid var(--color-border)' }}>
                  <User size={12} style={{ color: 'var(--color-blue)' }} />
                </div>
              )}
            </motion.div>
          ))}
        </AnimatePresence>

        {/* D: Agent typing indicator */}
        {agentTyping && !loading && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex justify-start gap-2">
            <div className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0"
                 style={{ background: 'var(--color-surface-2)', border: '1px solid var(--color-border)' }}>
              <Headset size={12} style={{ color: 'var(--color-green)' }} />
            </div>
            <div className="px-4 py-3 rounded-2xl flex items-center gap-1.5"
                 style={{ background: 'var(--color-surface-2)', border: '1px solid var(--color-border)' }}>
              <span className="w-1.5 h-1.5 rounded-full animate-bounce" style={{ background: 'var(--color-green)', animationDelay: '0ms' }} />
              <span className="w-1.5 h-1.5 rounded-full animate-bounce" style={{ background: 'var(--color-green)', animationDelay: '150ms' }} />
              <span className="w-1.5 h-1.5 rounded-full animate-bounce" style={{ background: 'var(--color-green)', animationDelay: '300ms' }} />
            </div>
          </motion.div>
        )}

        {loading && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex justify-start gap-2">
            <div className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0"
                 style={{ background: 'var(--color-surface-2)', border: '1px solid var(--color-border)' }}>
              <Bot size={12} style={{ color: 'var(--color-pink)' }} />
            </div>
            <div className="px-4 py-3 rounded-2xl flex items-center gap-2"
                 style={{ background: 'var(--color-surface-2)', border: '1px solid var(--color-border)' }}>
              <Loader2 size={13} className="animate-spin" style={{ color: 'var(--color-pink)' }} />
              {/* F1: Show real-time tool progress hint, fall back to generic text */}
              <motion.span key={progressText} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}
                className="text-[12px]" style={{ color: 'var(--color-muted)' }}>
                {progressText || '客服回复中…'}
              </motion.span>
            </div>
          </motion.div>
        )}
        <div ref={bottomRef} />
      </div>}

      {/* Quick prompts — styled as tappable pills, not passive tags */}
      {!historyView && messages.length === 1 && (
        <div className="px-4 pb-2 flex flex-wrap gap-1.5 shrink-0">
          {QUICK.map(p => (
            <motion.button key={p} onClick={() => send(p)}
              whileHover={{ scale: 1.04, borderColor: 'var(--color-pink)' }}
              whileTap={{ scale: 0.96 }}
              className="text-[11px] px-3 py-1.5 rounded-full border font-medium transition-colors"
              style={{ borderColor: 'var(--color-border)', color: 'var(--color-text)', background: 'var(--color-surface-2)', cursor: 'pointer' }}>
              {p}
            </motion.button>
          ))}
        </div>
      )}

      {/* Input */}
      {!historyView && <div className="px-4 py-3 border-t shrink-0"
           style={{ borderColor: 'var(--color-border)', background: 'var(--color-surface-2)' }}>

        {/* Image preview strip */}
        <AnimatePresence>
          {imagePreview && (
            <motion.div
              initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }}
              className="mb-2 flex items-start gap-2">
              <div className="relative rounded-xl overflow-hidden shrink-0"
                   style={{ border: '1px solid var(--color-border)' }}>
                <img src={imagePreview.dataUrl} alt="预览" className="h-20 w-auto object-cover rounded-xl" />
                <button
                  onClick={() => setImagePreview(null)}
                  className="absolute top-1 right-1 w-5 h-5 rounded-full flex items-center justify-center"
                  style={{ background: 'rgba(0,0,0,0.55)', cursor: 'pointer' }}>
                  <X size={10} color="#fff" />
                </button>
              </div>
              <div className="flex-1 text-[11px] pt-1" style={{ color: 'var(--color-muted)' }}>
                <div className="font-medium truncate max-w-[160px]">{imagePreview.file.name}</div>
                <div className="mt-0.5">{(imagePreview.file.size / 1024).toFixed(0)} KB</div>
                <div className="mt-1 text-[10px]" style={{ color: 'var(--color-muted)', opacity: 0.7 }}>
                  可在下方输入说明文字后发送
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        <div className="flex items-center gap-2 rounded-xl border p-1.5"
             style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
          {/* Hidden file input */}
          <input ref={fileInputRef} type="file" accept="image/*" className="hidden" onChange={handleFileSelect} />
          {/* Image attach button */}
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            title="发送图片"
            className="w-8 h-8 rounded-lg flex items-center justify-center transition-all shrink-0 disabled:opacity-30"
            style={{
              background: imagePreview ? 'rgba(236,72,153,0.12)' : 'transparent',
              color: imagePreview ? 'var(--color-pink)' : 'var(--color-muted)',
              border: `1px solid ${imagePreview ? 'rgba(236,72,153,0.3)' : 'transparent'}`,
              cursor: 'pointer',
            }}>
            {uploading ? <Loader2 size={14} className="animate-spin" /> : <ImagePlus size={14} />}
          </button>
          <input
            ref={inputRef}
            value={input}
            onChange={handleInputChange}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                if (imagePreview) sendImage(); else send();
              }
            }}
            placeholder={imagePreview ? '添加说明（可选）后按 Enter 发送…' : '描述您的问题或需求…'}
            className="flex-1 bg-transparent py-1 px-1 text-[13px] outline-none"
            style={{ color: 'var(--color-text)' }}
          />
          <motion.button
            onClick={() => imagePreview ? sendImage() : send()}
            disabled={(!input.trim() && !imagePreview) || loading || uploading}
            whileHover={(!input.trim() && !imagePreview) || loading ? {} : { scale: 1.08 }}
            whileTap={(!input.trim() && !imagePreview) || loading ? {} : { scale: 0.92 }}
            className="w-9 h-9 rounded-lg flex items-center justify-center disabled:opacity-25 transition-all"
            style={{
              background: 'var(--color-pink)',
              boxShadow: (input.trim() || imagePreview) ? '0 0 12px var(--color-pink-glow)' : 'none',
            }}>
            {uploading ? <Loader2 size={14} color="#fff" className="animate-spin" /> : <Send size={14} color="#fff" />}
          </motion.button>
        </div>
      </div>}

      {/* E: CSAT rating modal — appears after ticket is resolved */}
      <AnimatePresence>
        {ratingSessionId && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 20 }}
            className="absolute bottom-20 left-0 right-0 mx-4 rounded-2xl border p-4 shadow-2xl"
            style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
            {ratingSubmitted ? (
              <div className="text-center text-sm py-1" style={{ color: 'var(--color-green)' }}>
                ✅ 感谢您的评价！
              </div>
            ) : (
              <>
                <p className="text-[12px] text-center mb-3" style={{ color: 'var(--color-muted)' }}>
                  本次服务已结束，请为我们的服务评分
                </p>
                <div className="flex justify-center gap-3">
                  {[1, 2, 3, 4, 5].map(star => (
                    <button key={star} onClick={() => submitRating(star)}
                      className="transition-transform hover:scale-125">
                      <Star size={24} style={{ color: 'var(--color-amber)', fill: 'var(--color-amber)' }} />
                    </button>
                  ))}
                </div>
                <button
                  onClick={() => setRatingSessionId(null)}
                  className="mt-2 w-full text-[10px] text-center"
                  style={{ color: 'var(--color-muted)' }}>
                  跳过
                </button>
              </>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function roleColor(role: string) {
  return ({ user: 'var(--color-blue)', bot: 'var(--color-pink)', agent: 'var(--color-green)', system: 'var(--color-muted)' } as Record<string, string>)[role] ?? 'var(--color-muted)';
}
function roleLabel(role: string) {
  return ({ user: '您', bot: '客服', agent: '客服', system: '系统' } as Record<string, string>)[role] ?? role;
}

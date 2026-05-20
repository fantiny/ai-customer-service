import React, { useEffect, useRef, useState } from 'react';
import { Send, Bot, User, Wrench, ChevronDown, ChevronRight, Trash2, Loader2 } from 'lucide-react';
import { useAdminChat } from './AdminChatContext';
import type { AdminChatMessage } from '../../types';

function ToolCallChip({ msg }: { msg: AdminChatMessage }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="my-1">
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-1.5 text-xs px-2 py-1 rounded border transition-colors"
        style={{
          background: 'rgba(99,102,241,0.08)',
          borderColor: 'rgba(99,102,241,0.25)',
          color: '#818cf8',
        }}
      >
        <Wrench size={11} />
        <span>AI 操作记录{msg.tool_name ? `：${msg.tool_name}` : ''}</span>
        {open ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
      </button>
      {open && (
        <pre
          className="mt-1 text-[10px] p-2 rounded overflow-x-auto whitespace-pre-wrap break-all"
          style={{ background: 'rgba(15,20,40,0.6)', color: '#94a3b8', border: '1px solid rgba(99,102,241,0.15)' }}
        >
          {msg.content}
        </pre>
      )}
    </div>
  );
}

function MessageBubble({ msg }: { msg: AdminChatMessage }) {
  if (msg.role === 'tool') return <ToolCallChip msg={msg} />;

  const isHuman = msg.role === 'human';
  return (
    <div className={`flex gap-2 ${isHuman ? 'flex-row-reverse' : 'flex-row'}`}>
      <div
        className="w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5"
        style={{
          background: isHuman ? 'rgba(99,102,241,0.2)' : 'rgba(16,185,129,0.15)',
          color: isHuman ? '#818cf8' : '#34d399',
        }}
      >
        {isHuman ? <User size={12} /> : <Bot size={12} />}
      </div>
      <div
        className={`max-w-[85%] text-xs leading-relaxed px-3 py-2 rounded-xl whitespace-pre-wrap break-words overflow-x-hidden ${isHuman ? 'rounded-tr-sm' : 'rounded-tl-sm'}`}
        style={{
          background: isHuman
            ? 'rgba(99,102,241,0.15)'
            : 'rgba(30,35,55,0.8)',
          color: 'var(--color-text)',
          border: isHuman ? 'none' : '1px solid rgba(255,255,255,0.06)',
        }}
      >
        {msg.content}
      </div>
    </div>
  );
}

interface Props {
  collapsed: boolean;
  onToggle: () => void;
}

export default function AdminChatPanel({ collapsed, onToggle }: Props) {
  const { messages, sectionContext, loading, sendMessage, clearThread } = useAdminChat();
  const [input, setInput] = useState('');
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  const handleSend = async () => {
    const text = input.trim();
    if (!text || loading) return;
    setInput('');
    await sendMessage(text);
  };

  const handleKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  if (collapsed) {
    return (
      <button
        onClick={onToggle}
        className="flex flex-col items-center justify-center gap-2 h-full w-full transition-opacity hover:opacity-80"
        style={{ color: 'var(--color-muted)' }}
      >
        <Bot size={20} style={{ color: '#34d399' }} />
        <span className="text-[10px] font-mono writing-mode-vertical" style={{ writingMode: 'vertical-rl' }}>
          AI 助手
        </span>
      </button>
    );
  }

  return (
    <div className="flex flex-col h-full" style={{ borderLeft: '1px solid var(--color-border)' }}>
      {/* Header */}
      <div
        className="flex items-center justify-between px-3 py-2.5 flex-shrink-0"
        style={{ borderBottom: '1px solid var(--color-border)', background: 'rgba(15,20,40,0.4)' }}
      >
        <div className="flex items-center gap-2">
          <Bot size={15} style={{ color: '#34d399' }} />
          <span className="text-xs font-semibold" style={{ color: 'var(--color-text)' }}>AI 助手</span>
          {messages.length > 0 && (
            <span
              className="text-[10px] px-1.5 py-0.5 rounded-full"
              style={{ background: 'rgba(16,185,129,0.15)', color: '#34d399' }}
            >
              {messages.filter(m => m.role !== 'tool').length} 条
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          {messages.length > 0 && (
            <button
              onClick={clearThread}
              title="清空会话"
              className="p-1 rounded transition-colors hover:bg-white/5"
              style={{ color: 'var(--color-muted)' }}
            >
              <Trash2 size={12} />
            </button>
          )}
          <button
            onClick={onToggle}
            className="p-1 rounded transition-colors hover:bg-white/5"
            style={{ color: 'var(--color-muted)' }}
          >
            <ChevronRight size={14} />
          </button>
        </div>
      </div>

      {/* Context strip */}
      {sectionContext && (
        <div
          className="px-3 py-1.5 text-[10px] font-mono truncate flex-shrink-0"
          style={{
            background: 'rgba(99,102,241,0.06)',
            borderBottom: '1px solid rgba(99,102,241,0.12)',
            color: '#6366f1',
          }}
          title={sectionContext}
        >
          {sectionContext.split('\n')[0]}
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-3 py-3 flex flex-col gap-2.5 min-h-0">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full gap-3 opacity-40">
            <Bot size={28} style={{ color: '#34d399' }} />
            <p className="text-xs text-center" style={{ color: 'var(--color-muted)' }}>
              在这里与 AI 对话<br/>AI 会看到当前区块的数据上下文
            </p>
          </div>
        )}
        {messages.map((m, i) => <MessageBubble key={i} msg={m} />)}
        {loading && (
          <div className="flex items-center gap-2 text-xs" style={{ color: 'var(--color-muted)' }}>
            <Loader2 size={13} className="animate-spin" style={{ color: '#34d399' }} />
            <span>AI 思考中…</span>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div
        className="px-3 py-2.5 flex-shrink-0"
        style={{ borderTop: '1px solid var(--color-border)', background: 'rgba(15,20,40,0.3)' }}
      >
        <div
          className="flex items-end gap-2 rounded-xl px-3 py-2"
          style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
        >
          <textarea
            ref={inputRef}
            rows={1}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKey}
            placeholder="和 AI 对话，或让 AI 帮你操作…"
            className="flex-1 bg-transparent text-xs resize-none outline-none leading-relaxed"
            style={{
              color: 'var(--color-text)',
              maxHeight: 80,
              overflowY: input.split('\n').length > 3 ? 'auto' : 'hidden',
            }}
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || loading}
            className="p-1.5 rounded-lg transition-all flex-shrink-0"
            style={{
              background: input.trim() && !loading ? '#34d399' : 'rgba(52,211,153,0.15)',
              color: input.trim() && !loading ? '#0b1220' : '#34d399',
              opacity: input.trim() && !loading ? 1 : 0.5,
            }}
          >
            <Send size={12} />
          </button>
        </div>
      </div>
    </div>
  );
}

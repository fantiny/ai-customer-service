import React, {
  createContext, useCallback, useContext, useRef, useState,
} from 'react';
import { sendAdminChat, getAdminChatHistory } from '../../lib/adminApi';
import type { AdminChatMessage } from '../../types';

interface AdminChatCtx {
  threadId: string | null;
  messages: AdminChatMessage[];
  sectionContext: string;
  loading: boolean;
  sendMessage: (text: string) => Promise<void>;
  injectContext: (ctx: string) => void;
  clearThread: () => void;
}

const Ctx = createContext<AdminChatCtx | null>(null);

export function AdminChatProvider({ children }: { children: React.ReactNode }) {
  const [threadId, setThreadId] = useState<string | null>(null);
  const [messages, setMessages] = useState<AdminChatMessage[]>([]);
  const [sectionContext, setSectionContext] = useState('');
  const [loading, setLoading] = useState(false);
  const threadRef = useRef<string | null>(null);
  threadRef.current = threadId;

  const injectContext = useCallback((ctx: string) => {
    setSectionContext(ctx);
  }, []);

  const sendMessage = useCallback(async (text: string) => {
    const payload = sectionContext
      ? `[CONTEXT]\n${sectionContext}\n\n[USER]\n${text}`
      : text;

    const userMsg: AdminChatMessage = {
      role: 'human',
      content: text,
      timestamp: new Date().toISOString(),
    };
    setMessages(prev => [...prev, userMsg]);
    setLoading(true);

    try {
      const res = await sendAdminChat(payload, threadRef.current ?? undefined);
      if (!threadRef.current) {
        setThreadId(res.thread_id);
        // Load full history for the new thread (may include tool messages)
        try {
          const hist = await getAdminChatHistory(res.thread_id);
          setMessages(hist.messages);
        } catch {
          // If history fetch fails, just show the reply
          const aiMsg: AdminChatMessage = {
            role: 'ai',
            content: res.reply,
            timestamp: new Date().toISOString(),
          };
          setMessages(prev => [...prev, aiMsg]);
        }
      } else {
        // For existing threads, append the AI reply (tool calls already displayed)
        const aiMsg: AdminChatMessage = {
          role: 'ai',
          content: res.reply,
          timestamp: new Date().toISOString(),
        };
        setMessages(prev => [...prev, aiMsg]);
      }
    } catch (err) {
      const errMsg: AdminChatMessage = {
        role: 'ai',
        content: `出错了：${err instanceof Error ? err.message : String(err)}`,
        timestamp: new Date().toISOString(),
      };
      setMessages(prev => [...prev, errMsg]);
    } finally {
      setLoading(false);
    }
  }, [sectionContext]);

  const clearThread = useCallback(() => {
    setThreadId(null);
    setMessages([]);
    setSectionContext('');
  }, []);

  return (
    <Ctx.Provider value={{ threadId, messages, sectionContext, loading, sendMessage, injectContext, clearThread }}>
      {children}
    </Ctx.Provider>
  );
}

export function useAdminChat(): AdminChatCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error('useAdminChat must be used inside AdminChatProvider');
  return ctx;
}

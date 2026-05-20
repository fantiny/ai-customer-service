import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import AgentWorkspace from './components/AgentWorkspace';
import CustomerPortal from './components/CustomerPortal';
import AdminPanel from './components/admin/AdminPanel';
import { resolveIdentity, listenForTokenInjection, type Identity } from './lib/auth';

type View = 'customer' | 'agent' | 'admin';

export default function App() {
  // Support ?view=agent URL param to open workspace directly (useful for dev/test shortcuts)
  const [view, setView] = useState<View>(() =>
    new URLSearchParams(window.location.search).get('view') === 'agent' ? 'agent' : 'customer'
  );
  // Customer identity — resolved from JWT or guest fallback.
  // Only passed to CustomerPortal; AgentWorkspace manages its own agent identity independently.
  const [identity, setIdentity] = useState<Identity>(() => resolveIdentity());
  // Customer portal's own session ID (internal to the customer view)
  const [sessionId, setSessionId] = useState<string | null>(null);

  // Listen for token injection from parent frame (iframe / SSO redirect)
  useEffect(() => {
    const cleanup = listenForTokenInjection((newIdentity) => {
      setIdentity(newIdentity);
      setSessionId(null); // reset session on re-login
    });
    return cleanup;
  }, []);

  return (
    <div className="min-h-screen font-sans" style={{ background: 'var(--color-bg)', color: 'var(--color-text)' }}>
      {/* Dev-only view switcher — in production, customer and agent would be separate URLs */}
      <div className="fixed top-2 right-2 z-50 flex gap-1">
        {(['customer', 'agent', 'admin'] as View[]).map(v => (
          <button key={v} onClick={() => setView(v)}
            className="text-[10px] px-2 py-1 rounded border font-bold transition-all"
            style={{
              background: view === v ? 'var(--color-pink)' : 'var(--color-surface)',
              color: view === v ? '#fff' : 'var(--color-muted)',
              borderColor: view === v ? 'var(--color-pink)' : 'var(--color-border)',
            }}>
            {v === 'customer' ? '前台' : v === 'agent' ? '后台' : '管理'}
          </button>
        ))}
      </div>

      <main className="h-screen overflow-hidden">
        <AnimatePresence mode="wait">
          {view === 'admin' ? (
            <motion.div key="admin"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.15 }}
              className="h-full">
              <AdminPanel />
            </motion.div>
          ) : view === 'customer' ? (
            <motion.div key="customer"
              initial={{ opacity: 0, scale: 0.97 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 1.02 }}
              transition={{ duration: 0.18 }}
              className="h-full flex items-center justify-center p-4">
              <div className="w-full max-w-sm h-[680px] rounded-2xl shadow-2xl overflow-hidden flex flex-col border"
                   style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
                {/* Customer portal: uses its own customer identity (JWT / guest).
                    No session state is shared with the agent workspace. */}
                <CustomerPortal
                  identity={identity}
                  sessionId={sessionId}
                  onSessionChange={setSessionId}
                />
              </div>
            </motion.div>
          ) : (
            <motion.div key="agent"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.15 }}
              className="h-full">
              {/* Agent workspace: manages its own agent identity (agentId / name).
                  "客户视角" is a pure read-only UI preview — no socket session joining. */}
              <AgentWorkspace />
            </motion.div>
          )}
        </AnimatePresence>
      </main>
    </div>
  );
}

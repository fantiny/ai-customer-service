import React, { useState } from 'react';
import { Menu, X, MessageSquare } from 'lucide-react';
import { AdminChatProvider } from './AdminChatContext';
import AdminChatPanel from './AdminChatPanel';
import AdminNavRail from './shared/AdminNavRail';
import OverviewSection from './OverviewSection';
import KnowledgeSection from './KnowledgeSection';
import RulesSection from './RulesSection';
import PromptsSection from './PromptsSection';
import DigestSection from './DigestSection';
import ProductsSection from './ProductsSection';
import type { AdminSection } from '../../types';

export default function AdminPanel() {
  const [section, setSection] = useState<AdminSection>('overview');
  const [chatCollapsed, setChatCollapsed] = useState(false);
  // Mobile: nav drawer / chat drawer visibility
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [mobileChatOpen, setMobileChatOpen] = useState(false);

  const handleNav = (s: AdminSection) => {
    setSection(s);
    setMobileNavOpen(false); // close drawer after selecting
  };

  return (
    <AdminChatProvider>
      <div
        className="flex h-screen overflow-hidden relative"
        style={{ background: 'var(--color-bg)', color: 'var(--color-text)' }}
      >
        {/* ── Mobile overlay backdrop ── */}
        {(mobileNavOpen || mobileChatOpen) && (
          <div
            className="fixed inset-0 z-20 bg-black/50 md:hidden"
            onClick={() => { setMobileNavOpen(false); setMobileChatOpen(false); }}
          />
        )}

        {/* ── Left nav — hidden on mobile unless drawer open ── */}
        <div
          className={[
            'flex-shrink-0 h-full z-30 transition-transform duration-200',
            // Desktop: always visible; Mobile: slide-in drawer
            'fixed md:relative',
            mobileNavOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0',
          ].join(' ')}
          style={{ top: 0, left: 0 }}
        >
          <AdminNavRail active={section} onChange={handleNav} />
        </div>

        {/* ── Main content ── */}
        <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
          {/* Mobile top bar */}
          <div
            className="flex md:hidden items-center justify-between px-4 h-12 border-b flex-shrink-0"
            style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
          >
            <button
              onClick={() => setMobileNavOpen(v => !v)}
              className="p-1.5 rounded-lg"
              style={{ color: 'var(--color-muted)' }}
            >
              <Menu size={18} />
            </button>
            <span className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
              缘梦婚纱 Admin
            </span>
            <button
              onClick={() => setMobileChatOpen(v => !v)}
              className="p-1.5 rounded-lg"
              style={{ color: 'var(--color-muted)' }}
            >
              <MessageSquare size={18} />
            </button>
          </div>

          {/* Section content */}
          <div className="flex-1 overflow-y-auto p-4 md:p-6">
            {section === 'overview'  && <OverviewSection onNavigate={setSection} />}
            {section === 'products'  && <ProductsSection />}
            {section === 'knowledge' && <KnowledgeSection />}
            {section === 'rules'     && <RulesSection />}
            {section === 'prompts'   && <PromptsSection />}
            {section === 'digest'    && <DigestSection />}
          </div>
        </div>

        {/* ── Right AI chat panel ──
            Desktop: always visible as sidebar
            Mobile: slide-in drawer from right                         ── */}
        <div
          className={[
            'flex flex-col flex-shrink-0 overflow-hidden transition-all duration-200 z-30',
            // Desktop: sidebar; Mobile: fixed drawer
            'fixed md:relative right-0 top-0 h-full md:h-auto',
            mobileChatOpen ? 'translate-x-0' : 'translate-x-full md:translate-x-0',
          ].join(' ')}
          style={{
            width: chatCollapsed ? 44 : 320,
            minWidth: chatCollapsed ? 44 : 320,
            maxWidth: chatCollapsed ? 44 : 320,
            borderLeft: '1px solid var(--color-border)',
            background: 'rgba(10,14,30,0.95)',
          }}
        >
          {/* Mobile close button */}
          <button
            className="md:hidden absolute top-3 right-3 z-10 p-1 rounded"
            style={{ color: 'var(--color-muted)' }}
            onClick={() => setMobileChatOpen(false)}
          >
            <X size={16} />
          </button>
          <AdminChatPanel
            collapsed={chatCollapsed}
            onToggle={() => setChatCollapsed(v => !v)}
          />
        </div>
      </div>
    </AdminChatProvider>
  );
}

import React, { useState } from 'react';
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

  return (
    <AdminChatProvider>
      <div
        className="flex h-screen overflow-hidden"
        style={{ background: 'var(--color-bg)', color: 'var(--color-text)' }}
      >
        {/* Left nav */}
        <AdminNavRail active={section} onChange={setSection} />

        {/* Main content */}
        <div className="flex-1 overflow-y-auto min-w-0 p-6">
          {section === 'overview' && <OverviewSection onNavigate={setSection} />}
          {section === 'products' && <ProductsSection />}
          {section === 'knowledge' && <KnowledgeSection />}
          {section === 'rules' && <RulesSection />}
          {section === 'prompts' && <PromptsSection />}
          {section === 'digest' && <DigestSection />}
        </div>

        {/* Right AI chat panel */}
        <div
          className="flex flex-col flex-shrink-0 transition-all duration-200 overflow-hidden"
          style={{
            width: chatCollapsed ? 44 : 320,
            minWidth: chatCollapsed ? 44 : 320,
            maxWidth: chatCollapsed ? 44 : 320,
            borderLeft: '1px solid var(--color-border)',
            background: 'rgba(10,14,30,0.7)',
          }}
        >
          <AdminChatPanel
            collapsed={chatCollapsed}
            onToggle={() => setChatCollapsed(v => !v)}
          />
        </div>
      </div>
    </AdminChatProvider>
  );
}

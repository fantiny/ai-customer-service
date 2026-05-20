import React from 'react';
import {
  LayoutDashboard, BookOpen, SlidersHorizontal, Brain, FileBarChart2, ShoppingBag,
} from 'lucide-react';
import type { AdminSection } from '../../../types';

const NAV_ITEMS: { id: AdminSection; label: string; icon: React.ReactNode; group: string }[] = [
  { id: 'overview',   label: '总览',     icon: <LayoutDashboard size={15} />,  group: '运营' },
  { id: 'products',   label: '商品管理', icon: <ShoppingBag size={15} />,      group: '准备' },
  { id: 'knowledge',  label: '知识库',   icon: <BookOpen size={15} />,         group: '准备' },
  { id: 'rules',      label: '规则',     icon: <SlidersHorizontal size={15} />, group: '准备' },
  { id: 'prompts',    label: '提示词',   icon: <Brain size={15} />,            group: '准备' },
  { id: 'digest',     label: '日终复盘', icon: <FileBarChart2 size={15} />,    group: '复盘' },
];

interface Props {
  active: AdminSection;
  onChange: (s: AdminSection) => void;
}

export default function AdminNavRail({ active, onChange }: Props) {
  const groups = Array.from(new Set(NAV_ITEMS.map(n => n.group)));

  return (
    <nav
      className="flex flex-col h-full py-4 px-3 gap-1 flex-shrink-0"
      style={{
        width: 200,
        borderRight: '1px solid var(--color-border)',
        background: 'rgba(15,20,40,0.6)',
      }}
    >
      {/* Brand */}
      <div className="px-2 pb-4 mb-1" style={{ borderBottom: '1px solid var(--color-border)' }}>
        <div className="text-sm font-bold tracking-tight" style={{ color: 'var(--color-text)' }}>
          缘梦婚纱
        </div>
        <div className="text-[10px] mt-0.5 font-mono" style={{ color: 'var(--color-muted)' }}>
          Admin Console
        </div>
      </div>

      {groups.map(group => (
        <div key={group} className="mb-2">
          <div
            className="text-[9px] font-bold uppercase tracking-widest px-2 mb-1"
            style={{ color: 'var(--color-muted)', opacity: 0.6 }}
          >
            {group}
          </div>
          {NAV_ITEMS.filter(n => n.group === group).map(item => (
            <button
              key={item.id}
              onClick={() => onChange(item.id)}
              className="w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-left transition-all text-xs font-medium"
              style={{
                background: active === item.id ? 'rgba(99,102,241,0.18)' : 'transparent',
                color: active === item.id ? '#818cf8' : 'var(--color-muted)',
                borderLeft: active === item.id ? '2px solid #6366f1' : '2px solid transparent',
              }}
            >
              <span style={{ opacity: active === item.id ? 1 : 0.7 }}>{item.icon}</span>
              {item.label}
            </button>
          ))}
        </div>
      ))}
    </nav>
  );
}

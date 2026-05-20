import React from 'react';

interface Props {
  label: string;
  value: number;
  total?: number;
  color?: string;
  showPercent?: boolean;
}

export default function RateBar({ label, value, total, color = '#6366f1', showPercent = true }: Props) {
  const pct = total ? Math.round((value / total) * 100) : value;
  return (
    <div className="flex flex-col gap-1">
      <div className="flex justify-between items-center">
        <span className="text-xs" style={{ color: 'var(--color-muted)' }}>{label}</span>
        <span className="text-xs font-mono font-semibold" style={{ color }}>
          {showPercent ? `${pct}%` : value}
        </span>
      </div>
      <div className="h-1.5 rounded-full" style={{ background: 'var(--color-border)' }}>
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${Math.min(pct, 100)}%`, background: color }}
        />
      </div>
    </div>
  );
}

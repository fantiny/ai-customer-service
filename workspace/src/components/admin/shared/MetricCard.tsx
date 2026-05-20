import React from 'react';

interface Props {
  label: string;
  value: string | number;
  sub?: string;
  color?: string;
  icon?: React.ReactNode;
}

export default function MetricCard({ label, value, sub, color = '#818cf8', icon }: Props) {
  return (
    <div
      className="rounded-xl p-4 flex flex-col gap-1"
      style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
    >
      <div className="flex items-center gap-2">
        {icon && <span style={{ color }}>{icon}</span>}
        <span className="text-[11px]" style={{ color: 'var(--color-muted)' }}>{label}</span>
      </div>
      <div className="text-2xl font-bold font-mono" style={{ color }}>{value}</div>
      {sub && <div className="text-[11px]" style={{ color: 'var(--color-muted)' }}>{sub}</div>}
    </div>
  );
}

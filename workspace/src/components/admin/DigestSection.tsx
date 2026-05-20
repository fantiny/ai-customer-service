import React, { useEffect, useState, useCallback } from 'react';
import { Sparkles, ChevronDown, ChevronRight, Loader2, BarChart3 } from 'lucide-react';
import { listDigests, getDigest, generateDigest, getAnalytics } from '../../lib/adminApi';
import type { Digest, AnalyticsData } from '../../types';
import SectionShell from './shared/SectionShell';
import RateBar from './shared/RateBar';
import MetricCard from './shared/MetricCard';

function SimpleBarChart({ data, color = '#6366f1' }: { data: { label: string; value: number }[]; color?: string }) {
  const max = Math.max(...data.map(d => d.value), 1);
  return (
    <div className="flex items-end gap-1.5 h-24">
      {data.map((d, i) => (
        <div key={i} className="flex flex-col items-center gap-1 flex-1 min-w-0">
          <div
            className="w-full rounded-sm transition-all"
            style={{ height: Math.max((d.value / max) * 80, 2), background: color, opacity: 0.8 }}
            title={`${d.label}: ${d.value}`}
          />
          <span className="text-[8px] truncate w-full text-center" style={{ color: 'var(--color-muted)', opacity: 0.6 }}>
            {d.label.slice(5)}
          </span>
        </div>
      ))}
    </div>
  );
}

export default function DigestSection() {
  const [digests, setDigests] = useState<Digest[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [detail, setDetail] = useState<Digest | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [genToast, setGenToast] = useState('');
  const [analytics, setAnalytics] = useState<AnalyticsData | null>(null);
  const [showCharts, setShowCharts] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listDigests(14);
      setDigests(res);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const loadDetail = useCallback(async (date: string) => {
    setLoadingDetail(true);
    setDetail(null);
    try {
      setDetail(await getDigest(date));
    } finally {
      setLoadingDetail(false);
    }
  }, []);

  useEffect(() => {
    if (selectedDate) loadDetail(selectedDate);
  }, [selectedDate, loadDetail]);

  const loadAnalytics = async () => {
    setShowCharts(v => {
      if (!v && !analytics) {
        getAnalytics(7).then(setAnalytics).catch(() => null);
      }
      return !v;
    });
  };

  const handleGenerate = async () => {
    setGenerating(true);
    try {
      const res = await generateDigest();
      setGenToast(`已生成 ${res.report_date}`);
      setTimeout(() => setGenToast(''), 3000);
      await load();
      setSelectedDate(res.report_date);
    } catch {
      setGenToast('生成失败，请重试');
      setTimeout(() => setGenToast(''), 3000);
    } finally {
      setGenerating(false);
    }
  };

  const sectionContext = detail
    ? `【日终复盘】${detail.report_date}\n摘要：${detail.summary_md.slice(0, 400)}`
    : `【日终复盘】最近 ${digests.length} 份日报`;

  const topCategories = analytics
    ? Object.entries(analytics.categories).sort((a, b) => b[1] - a[1]).slice(0, 5)
    : [];

  const dailyVolumeData = analytics?.daily_volume.map(d => ({ label: d.date, value: d.count })) ?? [];

  return (
    <SectionShell context={sectionContext}>
      <div className="flex flex-col gap-4">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-base font-bold" style={{ color: 'var(--color-text)' }}>日终复盘</h2>
            <p className="text-xs mt-0.5" style={{ color: 'var(--color-muted)' }}>AI 摘要 · 运营趋势 · 质量分析</p>
          </div>
          <div className="flex items-center gap-2">
            {genToast && (
              <span className="text-xs px-2 py-1 rounded" style={{ background: 'rgba(16,185,129,0.15)', color: '#34d399' }}>
                {genToast}
              </span>
            )}
            <button
              onClick={loadAnalytics}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg transition-all"
              style={{ background: 'rgba(99,102,241,0.12)', color: '#818cf8', border: '1px solid rgba(99,102,241,0.2)' }}
            >
              <BarChart3 size={12} />
              {showCharts ? '收起图表' : '展开分析'}
            </button>
            <button
              onClick={handleGenerate}
              disabled={generating}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg transition-all"
              style={{
                background: 'rgba(245,158,11,0.15)',
                color: '#f59e0b',
                border: '1px solid rgba(245,158,11,0.25)',
                opacity: generating ? 0.6 : 1,
              }}
            >
              {generating ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
              生成今日日报
            </button>
          </div>
        </div>

        {/* Analytics charts */}
        {showCharts && (
          <div
            className="rounded-xl p-4 flex flex-col gap-4"
            style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
          >
            {!analytics ? (
              <div className="flex items-center gap-2 text-xs" style={{ color: 'var(--color-muted)' }}>
                <Loader2 size={13} className="animate-spin" />加载分析数据…
              </div>
            ) : (
              <>
                <div className="grid grid-cols-4 gap-3">
                  <MetricCard label="7天会话" value={analytics.tickets} color="#6366f1" />
                  <MetricCard label="AI 解决" value={analytics.ai_resolved} color="#10b981" />
                  <MetricCard label="转人工" value={analytics.escalated_to_human} color="#f59e0b" />
                  <MetricCard
                    label="平均解决时长"
                    value={analytics.avg_resolution_minutes != null ? `${analytics.avg_resolution_minutes.toFixed(1)}m` : '—'}
                    color="#06b6d4"
                  />
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <div className="text-[11px] font-semibold mb-2" style={{ color: 'var(--color-muted)' }}>7天会话量趋势</div>
                    {dailyVolumeData.length > 0 && (
                      <SimpleBarChart data={dailyVolumeData} color="#6366f1" />
                    )}
                  </div>
                  <div>
                    <div className="text-[11px] font-semibold mb-2" style={{ color: 'var(--color-muted)' }}>意图分布 Top 5</div>
                    <div className="flex flex-col gap-1.5">
                      {topCategories.map(([label, count]) => (
                        <RateBar
                          key={label}
                          label={label}
                          value={count}
                          total={analytics.tickets || 1}
                          color="#06b6d4"
                        />
                      ))}
                    </div>
                  </div>
                </div>
              </>
            )}
          </div>
        )}

        <div className="flex gap-4">
          {/* Digest list */}
          <div
            className="flex flex-col gap-1 flex-shrink-0"
            style={{ width: 160 }}
          >
            <div className="text-[10px] font-bold uppercase tracking-widest px-1 mb-1" style={{ color: 'var(--color-muted)', opacity: 0.5 }}>
              最近日报
            </div>
            {loading
              ? [...Array(5)].map((_, i) => (
                  <div key={i} className="h-10 rounded-lg animate-pulse" style={{ background: 'var(--color-surface)' }} />
                ))
              : digests.length === 0 ? (
                  <p className="text-xs px-2" style={{ color: 'var(--color-muted)' }}>暂无日报，点击「生成今日日报」</p>
                )
              : digests.map(d => (
                  <button
                    key={d.digest_id}
                    onClick={() => setSelectedDate(d.report_date)}
                    className="text-left px-3 py-2.5 rounded-lg text-xs transition-all"
                    style={{
                      background: selectedDate === d.report_date ? 'rgba(99,102,241,0.18)' : 'transparent',
                      color: selectedDate === d.report_date ? '#818cf8' : 'var(--color-muted)',
                      borderLeft: selectedDate === d.report_date ? '2px solid #6366f1' : '2px solid transparent',
                    }}
                  >
                    <div className="font-medium">{d.report_date}</div>
                  </button>
                ))
            }
          </div>

          {/* Digest content */}
          <div className="flex-1 min-w-0">
            {!selectedDate ? (
              <div
                className="flex items-center justify-center h-40 rounded-xl"
                style={{ border: '1px dashed var(--color-border)' }}
              >
                <p className="text-xs" style={{ color: 'var(--color-muted)' }}>← 选择日报查看详情</p>
              </div>
            ) : loadingDetail ? (
              <div className="flex items-center gap-2 text-xs py-4" style={{ color: 'var(--color-muted)' }}>
                <Loader2 size={14} className="animate-spin" />加载中…
              </div>
            ) : detail ? (
              <div
                className="rounded-xl p-4 flex flex-col gap-3"
                style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
                    {detail.report_date} 日报
                  </span>
                  <span className="text-[10px] font-mono" style={{ color: 'var(--color-muted)' }}>
                    {new Date(detail.created_at).toLocaleString()}
                  </span>
                </div>

                {/* Metrics summary */}
                {detail.metrics && typeof detail.metrics === 'object' && Object.keys(detail.metrics).length > 0 && (
                  <div
                    className="grid grid-cols-3 gap-2 p-3 rounded-lg text-xs"
                    style={{ background: 'rgba(99,102,241,0.06)', border: '1px solid rgba(99,102,241,0.12)' }}
                  >
                    {Object.entries(detail.metrics).slice(0, 6).map(([k, v]) => (
                      <div key={k}>
                        <div className="opacity-50">{k}</div>
                        <div className="font-semibold font-mono" style={{ color: 'var(--color-text)' }}>
                          {String(v)}
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {/* AI summary markdown */}
                <div
                  className="text-xs leading-relaxed whitespace-pre-wrap"
                  style={{ color: 'var(--color-muted)' }}
                >
                  {detail.summary_md || '（暂无摘要）'}
                </div>
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </SectionShell>
  );
}

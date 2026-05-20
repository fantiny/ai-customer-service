import React, { useEffect, useState, useCallback } from 'react';
import { RefreshCw, Sparkles, Loader2, FileText, Zap, Users, Clock } from 'lucide-react';
import { getTodayMetrics, getSystemHealth, generateDigest } from '../../lib/adminApi';
import type { TodayMetrics, SystemHealth, AdminSection } from '../../types';
import SectionShell from './shared/SectionShell';
import MetricCard from './shared/MetricCard';
import WorkflowFlowchart from './WorkflowFlowchart';
import { useAdminChat } from './AdminChatContext';

interface Props {
  onNavigate: (s: AdminSection) => void;
}

export default function OverviewSection({ onNavigate }: Props) {
  const [metrics, setMetrics] = useState<TodayMetrics | null>(null);
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [loadingData, setLoadingData] = useState(true);

  const load = useCallback(async () => {
    setLoadingData(true);
    const [m, h] = await Promise.all([
      getTodayMetrics().catch(() => null),
      getSystemHealth().catch(() => null),
    ]);
    setMetrics(m);
    setHealth(h);
    setLoadingData(false);
  }, []);
  const [generatingDigest, setGeneratingDigest] = useState(false);
  const [digestToast, setDigestToast] = useState('');
  const { sendMessage } = useAdminChat();
  const [briefSent, setBriefSent] = useState(false);

  useEffect(() => { load(); }, [load]);

  // Auto-send proactive brief once data is loaded
  useEffect(() => {
    if (!loadingData && metrics && !briefSent) {
      setBriefSent(true);
      const ctx = [
        `今日会话：${metrics.total_sessions}，AI 解决：${metrics.ai_resolved}，转人工：${metrics.escalated_to_human}`,
        health ? `知识库：${health.with_embedding}/${health.total_documents} 已嵌入（${health.embedding_coverage}%）` : '',
        health ? `业务规则：${health.business_rules_count} 条` : '',
      ].filter(Boolean).join('；');
      sendMessage(`根据以下今日数据，给我一个运营简报，并指出最需要关注的问题：${ctx}`);
    }
  }, [loadingData, metrics, briefSent, sendMessage, health]);

  const handleGenerateDigest = async () => {
    setGeneratingDigest(true);
    try {
      const res = await generateDigest();
      setDigestToast(`日报已生成：${res.report_date}`);
      setTimeout(() => setDigestToast(''), 3000);
    } catch {
      setDigestToast('生成失败，请重试');
      setTimeout(() => setDigestToast(''), 3000);
    } finally {
      setGeneratingDigest(false);
    }
  };

  const aiResolutionRate = metrics && metrics.total_sessions > 0
    ? Math.round((metrics.ai_resolved / metrics.total_sessions) * 100)
    : 0;

  const sectionContext = metrics ? [
    `【总览】今日数据`,
    `总会话：${metrics.total_sessions}，AI 解决：${metrics.ai_resolved}（${aiResolutionRate}%），转人工：${metrics.escalated_to_human}`,
    metrics.avg_resolve_min != null ? `平均解决时长：${metrics.avg_resolve_min.toFixed(1)} 分钟` : '',
    health ? `知识库：${health.with_embedding}/${health.total_documents} 已嵌入，规则：${health.business_rules_count} 条` : '',
  ].filter(Boolean).join('\n') : '【总览】加载中';

  return (
    <SectionShell context={sectionContext}>
      <div className="flex flex-col gap-5">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-base font-bold" style={{ color: 'var(--color-text)' }}>运营总览</h2>
            <p className="text-xs mt-0.5" style={{ color: 'var(--color-muted)' }}>
              今日业务状态 · 点击流程节点跳转对应区块
            </p>
          </div>
          <div className="flex items-center gap-2">
            {digestToast && (
              <span className="text-xs px-2 py-1 rounded" style={{ background: 'rgba(16,185,129,0.15)', color: '#34d399' }}>
                {digestToast}
              </span>
            )}
            <button
              onClick={handleGenerateDigest}
              disabled={generatingDigest}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg transition-all"
              style={{
                background: 'rgba(245,158,11,0.15)',
                color: '#f59e0b',
                border: '1px solid rgba(245,158,11,0.25)',
                opacity: generatingDigest ? 0.6 : 1,
              }}
            >
              {generatingDigest ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
              生成今日日报
            </button>
          </div>
        </div>

        {/* KPI cards */}
        {loadingData ? (
          <div className="grid grid-cols-4 gap-3">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-24 rounded-xl animate-pulse" style={{ background: 'var(--color-surface)' }} />
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <MetricCard
              label="今日总会话"
              value={metrics?.total_sessions ?? 0}
              icon={<Users size={14} />}
              color="#6366f1"
            />
            <MetricCard
              label="AI 解决"
              value={`${metrics?.ai_resolved ?? 0}`}
              sub={`占比 ${aiResolutionRate}%`}
              icon={<Zap size={14} />}
              color="#10b981"
            />
            <MetricCard
              label="转人工"
              value={metrics?.escalated_to_human ?? 0}
              icon={<Users size={14} />}
              color="#f59e0b"
            />
            <MetricCard
              label="平均解决时长"
              value={metrics?.avg_resolve_min != null ? `${metrics.avg_resolve_min.toFixed(1)} min` : '—'}
              icon={<Clock size={14} />}
              color="#06b6d4"
            />
          </div>
        )}

        {/* Workflow Flowchart */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-xs font-semibold" style={{ color: 'var(--color-muted)' }}>业务流程健康图</h3>
            <button
              onClick={load}
              className="flex items-center gap-1 text-[10px] transition-colors hover:opacity-80 cursor-pointer"
              style={{ color: 'var(--color-muted)' }}
            >
              <RefreshCw size={10} />
              刷新
            </button>
          </div>
          <WorkflowFlowchart health={health} onNavigate={onNavigate} />
        </div>

        {/* System health summary */}
        {health && (
          <div
            className="grid grid-cols-3 gap-3 p-4 rounded-xl text-xs"
            style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
          >
            <div>
              <div style={{ color: 'var(--color-muted)' }}>知识库文档</div>
              <div className="font-semibold mt-0.5" style={{ color: 'var(--color-text)' }}>
                {health.total_documents} 篇
                <span className="ml-1 text-[10px]" style={{ color: health.embedding_coverage >= 80 ? '#10b981' : '#f59e0b' }}>
                  ({health.embedding_coverage}% 已嵌入)
                </span>
              </div>
            </div>
            <div>
              <div style={{ color: 'var(--color-muted)' }}>业务规则</div>
              <div className="font-semibold mt-0.5" style={{ color: 'var(--color-text)' }}>{health.business_rules_count} 条</div>
            </div>
            <div>
              <div style={{ color: 'var(--color-muted)' }}>自定义提示词节点</div>
              <div className="font-semibold mt-0.5" style={{ color: 'var(--color-text)' }}>{health.nodes_with_custom_prompts} 个</div>
            </div>
          </div>
        )}
      </div>
    </SectionShell>
  );
}

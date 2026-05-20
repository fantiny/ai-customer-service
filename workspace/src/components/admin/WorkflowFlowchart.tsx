import React from 'react';
import type { SystemHealth } from '../../types';
import type { AdminSection } from '../../types';

interface Node {
  id: string;
  label: string;
  sublabel?: string;
  x: number;
  y: number;
  w: number;
  h: number;
  color: string;
  section?: AdminSection;
  health?: 'ok' | 'warn' | 'error';
}

interface Edge {
  from: string;
  to: string;
  label?: string;
}

const HEALTH_COLOR = { ok: '#10b981', warn: '#f59e0b', error: '#ef4444' };

function getHealth(
  nodeId: string,
  health: SystemHealth | null,
): 'ok' | 'warn' | 'error' {
  if (!health) return 'ok';
  if (nodeId === 'knowledge') {
    if (health.with_embedding === 0 && health.total_documents > 0) return 'error';
    if (health.embedding_coverage < 80) return 'warn';
    return 'ok';
  }
  if (nodeId === 'operations') {
    // warn if no active sessions is suspicious (just show ok for now)
    return 'ok';
  }
  return 'ok';
}

interface Props {
  health: SystemHealth | null;
  onNavigate: (s: AdminSection) => void;
}

export default function WorkflowFlowchart({ health, onNavigate }: Props) {
  const W = 760;
  const H = 320;

  const phases: { label: string; x: number; w: number; color: string }[] = [
    { label: '准备阶段', x: 10, w: 200, color: 'rgba(99,102,241,0.07)' },
    { label: '日常运营', x: 230, w: 300, color: 'rgba(16,185,129,0.05)' },
    { label: '日终复盘', x: 550, w: 200, color: 'rgba(245,158,11,0.07)' },
  ];

  const nodes: Node[] = [
    {
      id: 'knowledge', label: '知识库', sublabel: health ? `${health.with_embedding}/${health.total_documents} 已嵌入` : '',
      x: 20, y: 110, w: 90, h: 44, color: '#6366f1', section: 'knowledge',
      health: getHealth('knowledge', health),
    },
    {
      id: 'rules', label: '规则配置', sublabel: health ? `${health.business_rules_count} 条` : '',
      x: 20, y: 175, w: 90, h: 44, color: '#8b5cf6', section: 'rules',
    },
    {
      id: 'prompts', label: '提示词', sublabel: health ? `${health.nodes_with_custom_prompts} 节点` : '',
      x: 120, y: 140, w: 90, h: 44, color: '#a78bfa', section: 'prompts',
    },
    {
      id: 'intake', label: '客户发起会话', sublabel: health ? `今日 ${health.active_sessions}` : '',
      x: 245, y: 40, w: 100, h: 44, color: '#06b6d4',
    },
    {
      id: 'ai', label: 'AI 自动接待', sublabel: '意图识别·路由',
      x: 245, y: 130, w: 100, h: 44, color: '#8b5cf6',
    },
    {
      id: 'ai_resolve', label: 'AI 解决', sublabel: '查询/FAQ/推荐',
      x: 365, y: 80, w: 88, h: 38, color: '#10b981',
    },
    {
      id: 'hitl', label: 'HITL 审批', sublabel: '订单操作',
      x: 365, y: 135, w: 88, h: 38, color: '#f59e0b',
    },
    {
      id: 'human', label: '转人工', sublabel: '复杂问题',
      x: 365, y: 195, w: 88, h: 38, color: '#ec4899',
    },
    {
      id: 'digest', label: '日报生成', sublabel: 'AI 摘要+分析',
      x: 565, y: 80, w: 100, h: 44, color: '#f59e0b', section: 'digest',
    },
    {
      id: 'improve', label: '优化改进', sublabel: '提示词/知识库/规则',
      x: 565, y: 175, w: 100, h: 44, color: '#6366f1',
    },
  ];

  const edges: Edge[] = [
    { from: 'knowledge', to: 'ai' },
    { from: 'rules', to: 'ai' },
    { from: 'prompts', to: 'ai' },
    { from: 'intake', to: 'ai' },
    { from: 'ai', to: 'ai_resolve' },
    { from: 'ai', to: 'hitl' },
    { from: 'ai', to: 'human' },
    { from: 'ai_resolve', to: 'digest' },
    { from: 'hitl', to: 'digest' },
    { from: 'human', to: 'digest' },
    { from: 'digest', to: 'improve' },
    { from: 'improve', to: 'knowledge', label: '补充' },
    { from: 'improve', to: 'prompts', label: '优化' },
  ];

  const nodeMap = Object.fromEntries(nodes.map(n => [n.id, n]));

  function cx(n: Node) { return n.x + n.w / 2; }
  function cy(n: Node) { return n.y + n.h / 2; }

  function edgePath(e: Edge): string {
    const a = nodeMap[e.from];
    const b = nodeMap[e.to];
    if (!a || !b) return '';
    const x1 = cx(a), y1 = cy(a), x2 = cx(b), y2 = cy(b);
    const dx = (x2 - x1) * 0.5;
    return `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`;
  }

  function edgeMid(e: Edge): { x: number; y: number } {
    const a = nodeMap[e.from];
    const b = nodeMap[e.to];
    if (!a || !b) return { x: 0, y: 0 };
    return { x: (cx(a) + cx(b)) / 2, y: (cy(a) + cy(b)) / 2 };
  }

  return (
    <div
      className="rounded-xl overflow-hidden"
      style={{ border: '1px solid var(--color-border)', background: 'rgba(15,20,40,0.4)' }}
    >
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        style={{ display: 'block', maxHeight: 320 }}
      >
        {/* Phase swimlanes */}
        {phases.map(p => (
          <g key={p.label}>
            <rect x={p.x} y={8} width={p.w} height={H - 16} rx={8}
              fill={p.color} stroke="rgba(255,255,255,0.04)" strokeWidth={1} />
            <text x={p.x + p.w / 2} y={26} textAnchor="middle"
              fontSize={9} fill="rgba(255,255,255,0.3)" fontFamily="monospace">
              {p.label}
            </text>
          </g>
        ))}

        {/* Edges */}
        <defs>
          <marker id="arr" markerWidth={6} markerHeight={6} refX={5} refY={3} orient="auto">
            <path d="M0,0 L0,6 L6,3 z" fill="rgba(255,255,255,0.2)" />
          </marker>
        </defs>
        {edges.map((e, i) => (
          <g key={i}>
            <path
              d={edgePath(e)}
              fill="none"
              stroke="rgba(255,255,255,0.12)"
              strokeWidth={1.5}
              markerEnd="url(#arr)"
            />
            {e.label && (
              <text
                x={edgeMid(e).x}
                y={edgeMid(e).y - 4}
                textAnchor="middle"
                fontSize={8}
                fill="rgba(255,255,255,0.3)"
                fontFamily="monospace"
              >
                {e.label}
              </text>
            )}
          </g>
        ))}

        {/* Nodes */}
        {nodes.map(n => {
          const hc = n.health ? HEALTH_COLOR[n.health] : null;
          const isClickable = !!n.section;
          return (
            <g
              key={n.id}
              onClick={() => n.section && onNavigate(n.section)}
              style={{ cursor: isClickable ? 'pointer' : 'default' }}
            >
              <rect
                x={n.x} y={n.y} width={n.w} height={n.h} rx={7}
                fill={`${n.color}22`}
                stroke={n.color}
                strokeWidth={isClickable ? 1.5 : 1}
                className={isClickable ? 'hover:opacity-80 transition-opacity' : ''}
              />
              <text x={cx(n)} y={n.y + 16} textAnchor="middle"
                fontSize={10} fontWeight="600" fill="#e2e8f0" fontFamily="sans-serif">
                {n.label}
              </text>
              {n.sublabel && (
                <text x={cx(n)} y={n.y + 30} textAnchor="middle"
                  fontSize={8} fill="rgba(255,255,255,0.4)" fontFamily="monospace">
                  {n.sublabel}
                </text>
              )}
              {hc && (
                <>
                  <circle cx={n.x + n.w - 8} cy={n.y + 8} r={4} fill={hc} />
                  {n.health !== 'ok' && (
                    <circle cx={n.x + n.w - 8} cy={n.y + 8} r={6}
                      fill="none" stroke={hc} strokeWidth={1} opacity={0.4} />
                  )}
                </>
              )}
              {isClickable && (
                <rect
                  x={n.x} y={n.y} width={n.w} height={n.h} rx={7}
                  fill="transparent"
                  stroke="transparent"
                />
              )}
            </g>
          );
        })}
      </svg>

      {/* Legend */}
      <div
        className="flex items-center gap-4 px-4 py-2 text-[10px] font-mono flex-wrap"
        style={{ borderTop: '1px solid var(--color-border)', color: 'var(--color-muted)' }}
      >
        <span className="font-semibold opacity-60">健康状态：</span>
        {Object.entries(HEALTH_COLOR).map(([k, v]) => (
          <span key={k} className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full inline-block" style={{ background: v }} />
            {k === 'ok' ? '正常' : k === 'warn' ? '注意' : '异常'}
          </span>
        ))}
        <span className="opacity-40">点击节点可跳转至对应区块</span>
      </div>
    </div>
  );
}

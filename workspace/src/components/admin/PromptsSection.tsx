import React, { useEffect, useState, useCallback } from 'react';
import { Pencil, Send, ChevronDown, ChevronRight, Loader2, History, RotateCcw } from 'lucide-react';
import { listPrompts, getPromptHistory, publishPrompt, activatePromptVersion } from '../../lib/adminApi';
import type { PromptHistory } from '../../types';
import SectionShell from './shared/SectionShell';

const NODE_LABELS: Record<string, string> = {
  faq_node:        'FAQ 知识查询',
  product_node:    '商品推荐',
  order_read_node: '订单查询',
  order_write_node:'订单操作',
  aftersales_node: '售后处理',
  general_node:    '通用对话',
  router_node:     '意图路由',
};

const PLACEHOLDERS: Record<string, string[]> = {
  faq_node:        ['{lang_rule}', '{strict_instruction}', '{context}', '{business_name}'],
  product_node:    ['{lang_rule}', '{business_name}'],
  order_read_node: ['{lang_rule}', '{result_message}', '{business_name}'],
  order_write_node:['{lang_rule}', '{business_name}', '{rush_info}'],
  aftersales_node: ['{lang_rule}', '{business_name}'],
  general_node:    ['{lang_rule}', '{business_name}'],
};

export default function PromptsSection() {
  const [nodes, setNodes] = useState<{ node_name: string; version: number; preview: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeNode, setActiveNode] = useState<string | null>(null);
  const [history, setHistory] = useState<PromptHistory | null>(null);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [publishing, setPublishing] = useState(false);
  const [publishToast, setPublishToast] = useState('');
  const [errorMsg, setErrorMsg] = useState('');
  const [rollingBack, setRollingBack] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const [previewVersion, setPreviewVersion] = useState<{ content: string; version: number } | null>(null);

  const showError = (msg: string) => {
    setErrorMsg(msg);
    setTimeout(() => setErrorMsg(''), 4000);
  };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setNodes(await listPrompts());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const loadHistory = useCallback(async (node: string) => {
    setLoadingHistory(true);
    setHistory(null);
    setEditing(false);
    setDraft('');
    setShowHistory(false);
    setPreviewVersion(null);
    try {
      const h = await getPromptHistory(node);
      setHistory(h);
      setDraft(h.active_content);
    } catch {
      showError('加载提示词失败，请重试');
    } finally {
      setLoadingHistory(false);
    }
  }, []);

  const handleSelectNode = (node: string) => {
    setActiveNode(node);
    loadHistory(node);
  };

  const handlePublish = async () => {
    if (!activeNode || !draft.trim()) return;
    setPublishing(true);
    try {
      const res = await publishPrompt(activeNode, draft);
      setPublishToast(`已发布 v${res.version}`);
      setTimeout(() => setPublishToast(''), 3000);
      setEditing(false);
      await loadHistory(activeNode);
      await load();
    } catch {
      showError('发布失败，请重试');
    } finally {
      setPublishing(false);
    }
  };

  const handleRollback = async (promptId: string) => {
    if (!activeNode) return;
    setRollingBack(promptId);
    try {
      const res = await activatePromptVersion(activeNode, promptId);
      setPublishToast(`已回滚至 v${res.version}`);
      setTimeout(() => setPublishToast(''), 3000);
      setShowHistory(false);
      setPreviewVersion(null);
      await loadHistory(activeNode);
      await load();
    } catch {
      showError('回滚失败，请重试');
    } finally {
      setRollingBack(null);
    }
  };

  const sectionContext = history
    ? `【提示词配置】节点：${activeNode} 版本 v${history.active_version}\n当前提示词（前500字）：${history.active_content.slice(0, 500)}\n可用占位符：${(PLACEHOLDERS[activeNode ?? ''] ?? []).join(', ')}`
    : nodes.length > 0
      ? `【提示词配置】节点：${nodes.map(n => n.node_name).join(', ')}`
      : '【提示词配置】加载中';

  return (
    <SectionShell context={sectionContext}>
      <div className="flex gap-4 h-full min-h-0">
        {/* Node list */}
        <div
          className="flex flex-col gap-1 flex-shrink-0"
          style={{ width: 180 }}
        >
          <div className="text-[10px] font-bold uppercase tracking-widest px-2 mb-1" style={{ color: 'var(--color-muted)', opacity: 0.5 }}>
            节点
          </div>
          {loading
            ? [...Array(5)].map((_, i) => (
                <div key={i} className="h-8 rounded-lg animate-pulse" style={{ background: 'var(--color-surface)' }} />
              ))
            : nodes.map(n => (
                <button
                  key={n.node_name}
                  onClick={() => handleSelectNode(n.node_name)}
                  className="text-left px-3 py-2 rounded-lg text-xs transition-all"
                  style={{
                    background: activeNode === n.node_name ? 'rgba(99,102,241,0.18)' : 'transparent',
                    color: activeNode === n.node_name ? '#818cf8' : 'var(--color-muted)',
                    borderLeft: activeNode === n.node_name ? '2px solid #6366f1' : '2px solid transparent',
                  }}
                >
                  <div className="font-medium">{NODE_LABELS[n.node_name] ?? n.node_name}</div>
                  <div className="text-[10px] font-mono opacity-60">v{n.version}</div>
                </button>
              ))
          }
        </div>

        {/* Editor */}
        <div className="flex-1 flex flex-col gap-3 min-w-0">
          {!activeNode ? (
            <div
              className="flex-1 flex items-center justify-center rounded-xl"
              style={{ border: '1px dashed var(--color-border)' }}
            >
              <p className="text-xs" style={{ color: 'var(--color-muted)' }}>← 选择左侧节点查看提示词</p>
            </div>
          ) : loadingHistory ? (
            <div className="flex items-center gap-2 text-xs py-4" style={{ color: 'var(--color-muted)' }}>
              <Loader2 size={14} className="animate-spin" />加载中…
            </div>
          ) : history ? (
            <>
              {/* Top bar */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
                    {NODE_LABELS[activeNode] ?? activeNode}
                  </span>
                  <span
                    className="text-[10px] px-1.5 py-0.5 rounded font-mono"
                    style={{ background: 'rgba(99,102,241,0.15)', color: '#818cf8' }}
                  >
                    v{history.active_version}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  {errorMsg && (
                    <span className="text-xs px-2 py-1 rounded" style={{ background: 'rgba(239,68,68,0.15)', color: '#f87171' }}>
                      {errorMsg}
                    </span>
                  )}
                  {publishToast && (
                    <span className="text-xs px-2 py-1 rounded" style={{ background: 'rgba(16,185,129,0.15)', color: '#34d399' }}>
                      {publishToast}
                    </span>
                  )}
                  <button
                    onClick={() => setShowHistory(v => !v)}
                    className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg transition-all"
                    style={{ color: 'var(--color-muted)', background: 'rgba(255,255,255,0.04)' }}
                  >
                    <History size={12} />
                    历史 ({history.history.length})
                    {showHistory ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
                  </button>
                  {!editing ? (
                    <button
                      onClick={() => setEditing(true)}
                      className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg"
                      style={{ background: 'rgba(99,102,241,0.15)', color: '#818cf8', border: '1px solid rgba(99,102,241,0.25)' }}
                    >
                      <Pencil size={12} />编辑
                    </button>
                  ) : (
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => { setEditing(false); setDraft(history.active_content); }}
                        className="text-xs px-3 py-1.5 rounded-lg"
                        style={{ color: 'var(--color-muted)' }}
                      >
                        取消
                      </button>
                      <button
                        onClick={handlePublish}
                        disabled={publishing || draft.trim() === history.active_content}
                        className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg transition-all"
                        style={{
                          background: 'rgba(16,185,129,0.18)',
                          color: '#34d399',
                          border: '1px solid rgba(16,185,129,0.3)',
                          opacity: publishing || draft.trim() === history.active_content ? 0.5 : 1,
                        }}
                      >
                        {publishing ? <Loader2 size={12} className="animate-spin" /> : <Send size={12} />}
                        发布
                      </button>
                    </div>
                  )}
                </div>
              </div>

              {/* Placeholders hint */}
              {editing && PLACEHOLDERS[activeNode] && (
                <div
                  className="text-[10px] px-3 py-2 rounded-lg font-mono"
                  style={{ background: 'rgba(99,102,241,0.06)', color: '#818cf8', border: '1px solid rgba(99,102,241,0.15)' }}
                >
                  可用占位符：{PLACEHOLDERS[activeNode].join('  ')}
                </div>
              )}

              {/* History panel */}
              {showHistory && (
                <div
                  className="rounded-xl p-3 flex flex-col gap-2 max-h-40 overflow-y-auto"
                  style={{ background: 'rgba(15,20,40,0.5)', border: '1px solid var(--color-border)' }}
                >
                  {history.history.map(h => (
                    <div key={h.prompt_id} className="flex items-center gap-1">
                      <button
                        onClick={() => setPreviewVersion(previewVersion?.version === h.version ? null : { content: h.content, version: h.version })}
                        className="flex items-start gap-2 text-left text-xs px-2 py-1.5 rounded-lg transition-colors hover:bg-white/5 flex-1 min-w-0"
                        style={{ color: 'var(--color-muted)' }}
                      >
                        <span
                          className="font-mono px-1.5 py-0.5 rounded text-[10px] flex-shrink-0"
                          style={{ background: 'rgba(99,102,241,0.15)', color: '#818cf8' }}
                        >
                          v{h.version}
                        </span>
                        <span className="truncate flex-1">{h.content.slice(0, 80)}…</span>
                        <span className="text-[10px] opacity-40 flex-shrink-0">
                          {h.created_at ? new Date(h.created_at).toLocaleDateString() : ''}
                        </span>
                      </button>
                      {h.version !== history.active_version && (
                        <button
                          onClick={() => handleRollback(h.prompt_id)}
                          disabled={rollingBack === h.prompt_id}
                          title="回滚至此版本"
                          className="flex-shrink-0 p-1 rounded-md transition-colors hover:bg-amber-500/10"
                          style={{ color: 'rgba(245,158,11,0.6)' }}
                        >
                          {rollingBack === h.prompt_id
                            ? <Loader2 size={11} className="animate-spin" />
                            : <RotateCcw size={11} />}
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {/* Preview old version */}
              {previewVersion && (
                <div
                  className="rounded-xl p-3"
                  style={{ background: 'rgba(245,158,11,0.05)', border: '1px solid rgba(245,158,11,0.2)' }}
                >
                  <div className="text-[10px] mb-1.5" style={{ color: '#f59e0b' }}>
                    预览 v{previewVersion.version}（只读）
                  </div>
                  <pre className="text-[11px] whitespace-pre-wrap font-mono" style={{ color: 'var(--color-muted)' }}>
                    {previewVersion.content}
                  </pre>
                </div>
              )}

              {/* Editor / viewer */}
              {editing ? (
                <textarea
                  className="flex-1 w-full text-xs p-3 rounded-xl outline-none resize-none font-mono leading-relaxed"
                  style={{
                    background: 'rgba(15,20,40,0.6)',
                    border: '1px solid rgba(99,102,241,0.3)',
                    color: 'var(--color-text)',
                    minHeight: 260,
                  }}
                  value={draft}
                  onChange={e => setDraft(e.target.value)}
                />
              ) : (
                <pre
                  className="flex-1 text-xs p-4 rounded-xl overflow-y-auto whitespace-pre-wrap font-mono leading-relaxed"
                  style={{
                    background: 'rgba(15,20,40,0.5)',
                    border: '1px solid var(--color-border)',
                    color: 'var(--color-muted)',
                    minHeight: 260,
                  }}
                >
                  {history.active_content || <span className="opacity-40">（暂无自定义提示词，使用系统默认）</span>}
                </pre>
              )}
            </>
          ) : null}
        </div>
      </div>
    </SectionShell>
  );
}

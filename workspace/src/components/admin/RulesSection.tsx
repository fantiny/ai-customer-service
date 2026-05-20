import React, { useEffect, useState, useCallback } from 'react';
import { Plus, Save, Trash2, Loader2, Check, Clock, ChevronUp, ChevronDown } from 'lucide-react';
import { listRules, updateRule, deleteRule, getRuleHistory } from '../../lib/adminApi';
import type { BusinessRule } from '../../types';
import type { RuleAuditEntry } from '../../lib/adminApi';
import SectionShell from './shared/SectionShell';

function groupRules(rules: BusinessRule[]): Record<string, BusinessRule[]> {
  const out: Record<string, BusinessRule[]> = {};
  for (const r of rules) {
    const prefix = r.rule_key.includes('.') ? r.rule_key.split('.')[0] : '其他';
    (out[prefix] ??= []).push(r);
  }
  return out;
}

const GROUP_COLORS: Record<string, string> = {
  handoff:         '#ec4899',
  sla:             '#f59e0b',
  proactive_hint:  '#10b981',
  其他:            '#6366f1',
};

export default function RulesSection() {
  const [rules, setRules] = useState<BusinessRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [edits, setEdits] = useState<Record<string, { value: string; desc: string }>>({});
  const [saving, setSaving] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [newKey, setNewKey] = useState('');
  const [newVal, setNewVal] = useState('');
  const [newDesc, setNewDesc] = useState('');
  const [savingNew, setSavingNew] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');
  // Audit history state
  const [historyOpen, setHistoryOpen] = useState<string | null>(null);  // rule_key of open history panel
  const [historyData, setHistoryData] = useState<Record<string, RuleAuditEntry[]>>({});
  const [historyLoading, setHistoryLoading] = useState(false);

  const showError = (msg: string) => {
    setErrorMsg(msg);
    setTimeout(() => setErrorMsg(''), 4000);
  };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setRules(await listRules());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleSave = async (rule: BusinessRule) => {
    const e = edits[rule.rule_key];
    if (!e) return;
    setSaving(rule.rule_key);
    try {
      await updateRule(rule.rule_key, e.value, e.desc);
      setSaved(rule.rule_key);
      setTimeout(() => setSaved(null), 2000);
      setEdits(prev => {
        const next = { ...prev };
        delete next[rule.rule_key];
        return next;
      });
      await load();
    } catch {
      showError(`保存 ${rule.rule_key} 失败，请重试`);
    } finally {
      setSaving(null);
    }
  };

  const handleDelete = async (key: string) => {
    if (!confirm(`确认删除规则 ${key}？`)) return;
    try {
      await deleteRule(key);
      setRules(r => r.filter(x => x.rule_key !== key));
    } catch {
      showError(`删除 ${key} 失败，请重试`);
    }
  };

  const toggleHistory = async (key: string) => {
    if (historyOpen === key) {
      setHistoryOpen(null);
      return;
    }
    setHistoryOpen(key);
    if (historyData[key]) return; // already loaded
    setHistoryLoading(true);
    try {
      const res = await getRuleHistory(key);
      setHistoryData(prev => ({ ...prev, [key]: res.history }));
    } catch {
      setHistoryData(prev => ({ ...prev, [key]: [] }));
    } finally {
      setHistoryLoading(false);
    }
  };

  const handleCreate = async () => {
    if (!newKey.trim() || !newVal.trim()) return;
    setSavingNew(true);
    try {
      await updateRule(newKey.trim(), newVal.trim(), newDesc.trim());
      setShowNew(false);
      setNewKey(''); setNewVal(''); setNewDesc('');
      await load();
    } catch {
      showError('创建规则失败，请重试');
    } finally {
      setSavingNew(false);
    }
  };

  const groups = groupRules(rules);

  const sectionContext = rules.length > 0
    ? `【规则配置】当前 ${rules.length} 条规则\n` +
      rules.slice(0, 10).map(r => `${r.rule_key}="${r.rule_value}"`).join(', ') +
      (rules.length > 10 ? `…` : '')
    : '【规则配置】暂无规则';

  return (
    <SectionShell context={sectionContext}>
      <div className="flex flex-col gap-4">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-base font-bold" style={{ color: 'var(--color-text)' }}>规则配置</h2>
            <p className="text-xs mt-0.5" style={{ color: 'var(--color-muted)' }}>转人工话术 · SLA 阈值 · 主动提示 · 业务规则</p>
          </div>
          {errorMsg && (
            <span className="text-xs px-2 py-1 rounded" style={{ background: 'rgba(239,68,68,0.15)', color: '#f87171' }}>
              {errorMsg}
            </span>
          )}
          <button
            onClick={() => setShowNew(v => !v)}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg transition-all"
            style={{ background: 'rgba(99,102,241,0.15)', color: '#818cf8', border: '1px solid rgba(99,102,241,0.25)' }}
          >
            <Plus size={12} />
            添加规则
          </button>
        </div>

        {/* New rule form */}
        {showNew && (
          <div
            className="rounded-xl p-4 flex flex-col gap-3"
            style={{ background: 'var(--color-surface)', border: '1px solid rgba(99,102,241,0.3)' }}
          >
            <span className="text-xs font-semibold" style={{ color: '#818cf8' }}>新规则</span>
            <div className="grid grid-cols-2 gap-2">
              <input
                className="text-xs px-3 py-2 rounded-lg outline-none font-mono"
                style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                placeholder="rule_key (如 sla.hitl_minutes)"
                value={newKey}
                onChange={e => setNewKey(e.target.value)}
              />
              <input
                className="text-xs px-3 py-2 rounded-lg outline-none"
                style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                placeholder="值"
                value={newVal}
                onChange={e => setNewVal(e.target.value)}
              />
            </div>
            <input
              className="text-xs px-3 py-2 rounded-lg outline-none"
              style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
              placeholder="描述（可选）"
              value={newDesc}
              onChange={e => setNewDesc(e.target.value)}
            />
            <div className="flex justify-end gap-2">
              <button onClick={() => setShowNew(false)} className="text-xs px-3 py-1.5 rounded-lg" style={{ color: 'var(--color-muted)' }}>取消</button>
              <button
                onClick={handleCreate}
                disabled={savingNew || !newKey.trim() || !newVal.trim()}
                className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg"
                style={{ background: 'rgba(99,102,241,0.2)', color: '#818cf8', opacity: savingNew ? 0.5 : 1 }}
              >
                {savingNew ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
                保存
              </button>
            </div>
          </div>
        )}

        {loading ? (
          <div className="flex items-center gap-2 text-xs py-4" style={{ color: 'var(--color-muted)' }}>
            <Loader2 size={14} className="animate-spin" />加载中…
          </div>
        ) : (
          Object.entries(groups).map(([group, groupRules]) => {
            const color = GROUP_COLORS[group] ?? '#6366f1';
            return (
              <div key={group}>
                <div
                  className="text-[10px] font-bold uppercase tracking-widest px-1 mb-2 font-mono"
                  style={{ color }}
                >
                  {group}.*
                </div>
                <div
                  className="rounded-xl overflow-hidden"
                  style={{ border: '1px solid var(--color-border)' }}
                >
                  {groupRules.map((rule, idx) => {
                    const isDirty = !!edits[rule.rule_key];
                    const isSaving = saving === rule.rule_key;
                    const isSaved = saved === rule.rule_key;
                    const isHistoryOpen = historyOpen === rule.rule_key;
                    const entries = historyData[rule.rule_key] ?? [];
                    return (
                      <div
                        key={rule.rule_key}
                        style={{
                          borderTop: idx > 0 ? '1px solid var(--color-border)' : 'none',
                        }}
                      >
                        <div
                          className="flex items-start gap-3 px-4 py-3"
                          style={{
                            background: isDirty ? 'rgba(99,102,241,0.04)' : 'var(--color-surface)',
                          }}
                        >
                          <div className="flex-1 min-w-0 flex flex-col gap-1.5">
                            <div className="flex items-center gap-2">
                              <code className="text-[11px] font-mono" style={{ color }}>
                                {rule.rule_key}
                              </code>
                              {rule.description && (
                                <span className="text-[10px]" style={{ color: 'var(--color-muted)' }}>
                                  — {rule.description}
                                </span>
                              )}
                            </div>
                            <input
                              className="w-full text-xs px-2 py-1.5 rounded-lg outline-none"
                              style={{
                                background: 'rgba(255,255,255,0.04)',
                                border: `1px solid ${isDirty ? `${color}40` : 'var(--color-border)'}`,
                                color: 'var(--color-text)',
                                fontFamily: 'monospace',
                              }}
                              value={edits[rule.rule_key]?.value ?? rule.rule_value}
                              onChange={e =>
                                setEdits(prev => ({
                                  ...prev,
                                  [rule.rule_key]: { value: e.target.value, desc: prev[rule.rule_key]?.desc ?? rule.description },
                                }))
                              }
                            />
                          </div>
                          <div className="flex items-center gap-1 flex-shrink-0 pt-5">
                            {isDirty && (
                              <button
                                onClick={() => handleSave(rule)}
                                disabled={isSaving}
                                className="flex items-center gap-1 text-[11px] px-2.5 py-1.5 rounded-lg transition-all"
                                style={{ background: `${color}22`, color, border: `1px solid ${color}44` }}
                              >
                                {isSaving ? <Loader2 size={11} className="animate-spin" /> : <Save size={11} />}
                                保存
                              </button>
                            )}
                            {isSaved && (
                              <span className="text-[11px] flex items-center gap-1" style={{ color: '#10b981' }}>
                                <Check size={11} />已保存
                              </span>
                            )}
                            <button
                              onClick={() => toggleHistory(rule.rule_key)}
                              title="变更历史"
                              className="p-1.5 rounded-lg transition-colors"
                              style={{ color: isHistoryOpen ? '#f59e0b' : 'rgba(148,163,184,0.45)' }}
                            >
                              {isHistoryOpen ? <ChevronUp size={12} /> : <Clock size={12} />}
                            </button>
                            <button
                              onClick={() => handleDelete(rule.rule_key)}
                              className="p-1.5 rounded-lg transition-colors hover:bg-red-500/10"
                              style={{ color: 'rgba(239,68,68,0.45)' }}
                            >
                              <Trash2 size={12} />
                            </button>
                          </div>
                        </div>

                        {/* Audit history panel */}
                        {isHistoryOpen && (
                          <div
                            className="px-4 pb-3"
                            style={{ background: 'rgba(245,158,11,0.04)', borderTop: '1px solid rgba(245,158,11,0.15)' }}
                          >
                            <div className="flex items-center gap-1.5 py-2 text-[10px] font-bold uppercase tracking-widest" style={{ color: '#f59e0b' }}>
                              <Clock size={10} />
                              变更历史
                            </div>
                            {historyLoading && entries.length === 0 ? (
                              <div className="flex items-center gap-1.5 text-[11px] py-2" style={{ color: 'var(--color-muted)' }}>
                                <Loader2 size={11} className="animate-spin" />加载中…
                              </div>
                            ) : entries.length === 0 ? (
                              <div className="text-[11px] py-2 italic" style={{ color: 'var(--color-muted)' }}>暂无变更记录</div>
                            ) : (
                              <div className="flex flex-col gap-1.5 max-h-48 overflow-y-auto">
                                {entries.map((e) => (
                                  <div key={e.log_id} className="flex items-start gap-2 text-[11px]">
                                    <span
                                      className="shrink-0 px-1.5 py-0.5 rounded text-[9px] font-bold uppercase"
                                      style={{
                                        background: e.operation === 'delete' ? 'rgba(239,68,68,0.15)' : 'rgba(99,102,241,0.15)',
                                        color: e.operation === 'delete' ? '#f87171' : '#818cf8',
                                      }}
                                    >
                                      {e.operation === 'delete' ? '删除' : '修改'}
                                    </span>
                                    <div className="flex-1 min-w-0">
                                      {e.operation === 'set' && (
                                        <div className="font-mono truncate" style={{ color: 'var(--color-muted)' }}>
                                          {e.old_value != null && (
                                            <span style={{ color: '#f87171', textDecoration: 'line-through', marginRight: 4 }}>
                                              {e.old_value.length > 40 ? e.old_value.slice(0, 40) + '…' : e.old_value}
                                            </span>
                                          )}
                                          <span style={{ color: '#86efac' }}>
                                            {e.new_value ? (e.new_value.length > 40 ? e.new_value.slice(0, 40) + '…' : e.new_value) : '—'}
                                          </span>
                                        </div>
                                      )}
                                    </div>
                                    <span className="shrink-0 text-[10px]" style={{ color: 'var(--color-muted)' }}>
                                      {new Date(e.changed_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
                                    </span>
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })
        )}
      </div>
    </SectionShell>
  );
}

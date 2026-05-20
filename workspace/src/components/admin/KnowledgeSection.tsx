import React, { useEffect, useState, useCallback, useRef } from 'react';
import {
  Plus, RefreshCw, Zap, ChevronDown, ChevronRight, Pencil, Trash2,
  Loader2, CheckCircle2, AlertTriangle, X, Save, Search,
} from 'lucide-react';
import {
  listKnowledgeDocs, createKnowledgeDoc, updateKnowledgeDoc,
  deleteKnowledgeDoc, embedAllDocs, embedSingleDoc, agentKnowledgeSearch,
  type KBSearchResult,
} from '../../lib/adminApi';
import type { KnowledgeDoc } from '../../types';
import SectionShell from './shared/SectionShell';
import RateBar from './shared/RateBar';

type KnowledgeType = 'business_policy' | 'industry_knowledge';

const TYPE_BADGE: Record<KnowledgeType, { label: string; color: string; bg: string }> = {
  business_policy:    { label: '业务政策', color: '#ef4444', bg: 'rgba(239,68,68,0.12)' },
  industry_knowledge: { label: '行业知识', color: '#06b6d4', bg: 'rgba(6,182,212,0.1)' },
};

interface NewDocForm {
  title: string;
  content: string;
  category: string;
  knowledge_type: KnowledgeType;
}

// F5: KB Search Playground subcomponent
function SearchPlayground() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<KBSearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searched, setSearched] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const runSearch = useCallback(async (q: string) => {
    if (!q.trim()) { setResults([]); setSearched(false); return; }
    setSearching(true);
    try {
      const res = await agentKnowledgeSearch(q);
      setResults(res);
      setSearched(true);
    } finally {
      setSearching(false);
    }
  }, []);

  const handleInput = (v: string) => {
    setQuery(v);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => runSearch(v), 350);
  };

  return (
    <div className="rounded-xl p-4 flex flex-col gap-3"
         style={{ background: 'var(--color-surface)', border: '1px solid rgba(6,182,212,0.25)' }}>
      <div className="flex items-center gap-2">
        <Search size={13} style={{ color: '#06b6d4', flexShrink: 0 }} />
        <span className="text-xs font-semibold" style={{ color: '#06b6d4' }}>检索测试</span>
        <span className="text-[10px] ml-1" style={{ color: 'var(--color-muted)' }}>输入问题，查看 RAG 会命中哪些文档</span>
      </div>
      <div className="flex items-center gap-2 rounded-lg px-3 py-2 border"
           style={{ background: 'rgba(255,255,255,0.04)', borderColor: 'rgba(6,182,212,0.3)' }}>
        <input
          value={query}
          onChange={e => handleInput(e.target.value)}
          placeholder="例：退货政策是什么？"
          className="flex-1 bg-transparent text-xs outline-none"
          style={{ color: 'var(--color-text)' }}
        />
        {searching && <Loader2 size={11} className="animate-spin shrink-0" style={{ color: '#06b6d4' }} />}
      </div>
      {searched && results.length === 0 && (
        <p className="text-[11px] italic" style={{ color: 'var(--color-muted)' }}>未找到相关文档</p>
      )}
      {results.map((r, i) => (
        <div key={i} className="rounded-lg p-3 flex flex-col gap-1.5"
             style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid var(--color-border)' }}>
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-semibold truncate flex-1" style={{ color: 'var(--color-text)' }}>
              {r.title || '（无标题）'}
            </span>
            <span className="text-[9px] px-1.5 py-0.5 rounded font-bold shrink-0"
                  style={{
                    background: r.knowledge_type === 'business_policy' ? 'rgba(239,68,68,0.12)' : 'rgba(6,182,212,0.1)',
                    color: r.knowledge_type === 'business_policy' ? '#ef4444' : '#06b6d4',
                  }}>
              {r.knowledge_type === 'business_policy' ? 'POLICY' : 'KNOWLEDGE'}
            </span>
            {typeof r.score === 'number' && (
              <div className="flex items-center gap-1 shrink-0">
                <div className="w-16 h-1.5 rounded-full overflow-hidden" style={{ background: 'rgba(255,255,255,0.1)' }}>
                  <div className="h-full rounded-full" style={{ width: `${Math.round(r.score * 100)}%`, background: r.score > 0.7 ? '#10b981' : r.score > 0.4 ? '#f59e0b' : '#ef4444' }} />
                </div>
                <span className="text-[9px] font-mono" style={{ color: 'var(--color-muted)' }}>{r.score.toFixed(2)}</span>
              </div>
            )}
          </div>
          <p className="text-[10px] leading-relaxed line-clamp-3" style={{ color: 'var(--color-muted)' }}>
            {(r.snippet || '').slice(0, 120)}{(r.snippet || '').length > 120 ? '…' : ''}
          </p>
        </div>
      ))}
    </div>
  );
}

export default function KnowledgeSection() {
  const [docs, setDocs] = useState<KnowledgeDoc[]>([]);
  const [loading, setLoading] = useState(true);
  const [embeddingAll, setEmbeddingAll] = useState(false);
  const [embedToast, setEmbedToast] = useState('');
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState<Partial<KnowledgeDoc>>({});
  const [showNew, setShowNew] = useState(false);
  const [newDoc, setNewDoc] = useState<NewDocForm>({
    title: '', content: '', category: 'wedding_dress_faq', knowledge_type: 'industry_knowledge',
  });
  const [savingNew, setSavingNew] = useState(false);
  const [embeddingId, setEmbeddingId] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState('');

  const showError = (msg: string) => {
    setErrorMsg(msg);
    setTimeout(() => setErrorMsg(''), 4000);
  };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listKnowledgeDocs();
      setDocs(res);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const withEmbedding = docs.filter(d => d.has_embedding).length;
  const coverage = docs.length > 0 ? Math.round((withEmbedding / docs.length) * 100) : 0;
  const unembedded = docs.filter(d => !d.has_embedding);

  const handleEmbedAll = async () => {
    setEmbeddingAll(true);
    try {
      const res = await embedAllDocs();
      setEmbedToast(`成功嵌入 ${res.embedded}/${res.total} 篇`);
      await load();
    } catch {
      setEmbedToast('嵌入失败，请重试');
    } finally {
      setEmbeddingAll(false);
      setTimeout(() => setEmbedToast(''), 4000);
    }
  };

  const handleEmbedSingle = async (docId: string) => {
    setEmbeddingId(docId);
    try {
      await embedSingleDoc(docId);
      await load();
    } catch {
      showError('嵌入失败，请重试');
    } finally {
      setEmbeddingId(null);
    }
  };

  const handleDelete = async (docId: string) => {
    if (!confirm('确认删除该文档？')) return;
    try {
      await deleteKnowledgeDoc(docId);
      setDocs(d => d.filter(x => x.doc_id !== docId));
    } catch {
      showError('删除失败，请重试');
    }
  };

  const handleSaveEdit = async (doc: KnowledgeDoc) => {
    try {
      await updateKnowledgeDoc(doc.doc_id, editDraft);
      setEditingId(null);
      setEditDraft({});
      await load();
    } catch {
      showError('保存失败，请重试');
    }
  };

  const handleCreate = async () => {
    if (!newDoc.title.trim() || !newDoc.content.trim()) return;
    setSavingNew(true);
    try {
      await createKnowledgeDoc(newDoc);
      setShowNew(false);
      setNewDoc({ title: '', content: '', category: 'wedding_dress_faq', knowledge_type: 'industry_knowledge' });
      await load();
    } catch {
      showError('创建失败，请重试');
    } finally {
      setSavingNew(false);
    }
  };

  const sectionContext = [
    `【知识库管理】共 ${docs.length} 篇，${withEmbedding} 篇已嵌入（${coverage}%）`,
    unembedded.length > 0
      ? `未嵌入：${unembedded.slice(0, 5).map(d => d.title).join('、')}${unembedded.length > 5 ? `…共 ${unembedded.length} 篇` : ''}`
      : '全部已嵌入',
    `业务政策：${docs.filter(d => d.knowledge_type === 'business_policy').length} 篇，行业知识：${docs.filter(d => d.knowledge_type === 'industry_knowledge').length} 篇`,
  ].join('\n');

  return (
    <SectionShell context={sectionContext}>
      <div className="flex flex-col gap-4">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-base font-bold" style={{ color: 'var(--color-text)' }}>知识库管理</h2>
            <p className="text-xs mt-0.5" style={{ color: 'var(--color-muted)' }}>FAQ 文档 · 业务政策 · 行业知识</p>
          </div>
          <div className="flex items-center gap-2">
            {errorMsg && (
              <span className="text-xs px-2 py-1 rounded" style={{ background: 'rgba(239,68,68,0.15)', color: '#f87171' }}>
                {errorMsg}
              </span>
            )}
            {embedToast && (
              <span className="text-xs px-2 py-1 rounded" style={{ background: 'rgba(16,185,129,0.15)', color: '#34d399' }}>
                {embedToast}
              </span>
            )}
            <button
              onClick={() => setShowNew(v => !v)}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg transition-all"
              style={{ background: 'rgba(99,102,241,0.15)', color: '#818cf8', border: '1px solid rgba(99,102,241,0.25)' }}
            >
              <Plus size={12} />
              添加文档
            </button>
            <button
              onClick={handleEmbedAll}
              disabled={embeddingAll}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg transition-all"
              style={{
                background: unembedded.length > 0 ? 'rgba(245,158,11,0.18)' : 'rgba(16,185,129,0.12)',
                color: unembedded.length > 0 ? '#f59e0b' : '#34d399',
                border: `1px solid ${unembedded.length > 0 ? 'rgba(245,158,11,0.3)' : 'rgba(16,185,129,0.2)'}`,
                opacity: embeddingAll ? 0.6 : 1,
              }}
            >
              {embeddingAll ? <Loader2 size={12} className="animate-spin" /> : <Zap size={12} />}
              全部重新嵌入
            </button>
          </div>
        </div>

        {/* Coverage bar */}
        <div
          className="px-4 py-3 rounded-xl"
          style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
        >
          <RateBar
            label={`嵌入覆盖率 (${withEmbedding}/${docs.length})`}
            value={coverage}
            color={coverage === 100 ? '#10b981' : coverage >= 80 ? '#f59e0b' : '#ef4444'}
          />
          {unembedded.length > 0 && (
            <div className="mt-2 flex items-center gap-1.5 text-xs" style={{ color: '#f59e0b' }}>
              <AlertTriangle size={11} />
              <span>{unembedded.length} 篇文档未嵌入，检索效果受影响</span>
            </div>
          )}
        </div>

        {/* F5: KB Search Playground */}
        <SearchPlayground />

        {/* New doc form */}
        {showNew && (
          <div
            className="rounded-xl p-4 flex flex-col gap-3"
            style={{ background: 'var(--color-surface)', border: '1px solid rgba(99,102,241,0.3)' }}
          >
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold" style={{ color: '#818cf8' }}>新建文档</span>
              <button onClick={() => setShowNew(false)} style={{ color: 'var(--color-muted)' }}>
                <X size={14} />
              </button>
            </div>
            <input
              className="w-full text-xs px-3 py-2 rounded-lg outline-none"
              style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
              placeholder="文档标题"
              value={newDoc.title}
              onChange={e => setNewDoc(v => ({ ...v, title: e.target.value }))}
            />
            <div className="flex gap-2">
              <select
                className="text-xs px-2 py-1.5 rounded-lg outline-none flex-1"
                style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                value={newDoc.knowledge_type}
                onChange={e => setNewDoc(v => ({ ...v, knowledge_type: e.target.value as KnowledgeType }))}
              >
                <option value="industry_knowledge">行业知识</option>
                <option value="business_policy">业务政策</option>
              </select>
              <input
                className="text-xs px-2 py-1.5 rounded-lg outline-none flex-1"
                style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                placeholder="分类 (如 wedding_dress_faq)"
                value={newDoc.category}
                onChange={e => setNewDoc(v => ({ ...v, category: e.target.value }))}
              />
            </div>
            <textarea
              rows={5}
              className="w-full text-xs px-3 py-2 rounded-lg outline-none resize-y"
              style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
              placeholder="文档内容"
              value={newDoc.content}
              onChange={e => setNewDoc(v => ({ ...v, content: e.target.value }))}
            />
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setShowNew(false)}
                className="text-xs px-3 py-1.5 rounded-lg"
                style={{ color: 'var(--color-muted)' }}
              >
                取消
              </button>
              <button
                onClick={handleCreate}
                disabled={savingNew || !newDoc.title.trim()}
                className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg transition-all"
                style={{
                  background: 'rgba(99,102,241,0.2)',
                  color: '#818cf8',
                  border: '1px solid rgba(99,102,241,0.3)',
                  opacity: savingNew || !newDoc.title.trim() ? 0.5 : 1,
                }}
              >
                {savingNew ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
                保存
              </button>
            </div>
          </div>
        )}

        {/* Doc list */}
        {loading ? (
          <div className="flex items-center gap-2 text-xs py-4" style={{ color: 'var(--color-muted)' }}>
            <Loader2 size={14} className="animate-spin" />
            加载中…
          </div>
        ) : (
          <div className="flex flex-col gap-1.5">
            {docs.map(doc => {
              const badge = TYPE_BADGE[doc.knowledge_type];
              const isExpanded = expandedId === doc.doc_id;
              const isEditing = editingId === doc.doc_id;
              return (
                <div
                  key={doc.doc_id}
                  className="rounded-xl overflow-hidden"
                  style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
                >
                  {/* Row header */}
                  <div
                    className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-white/[0.02] transition-colors"
                    onClick={() => setExpandedId(isExpanded ? null : doc.doc_id)}
                  >
                    <span style={{ color: 'var(--color-muted)', opacity: 0.5 }}>
                      {isExpanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                    </span>
                    <span
                      className="text-[10px] px-1.5 py-0.5 rounded font-semibold flex-shrink-0"
                      style={{ background: badge.bg, color: badge.color }}
                    >
                      {badge.label}
                    </span>
                    <span className="text-xs font-medium flex-1 truncate" style={{ color: 'var(--color-text)' }}>
                      {doc.title}
                    </span>
                    {doc.preview && !isExpanded && (
                      <span className="text-[11px] truncate max-w-[240px] hidden lg:block" style={{ color: 'var(--color-muted)' }}>
                        {doc.preview}
                      </span>
                    )}
                    <div className="flex items-center gap-2 flex-shrink-0">
                      {doc.has_embedding ? (
                        <span className="flex items-center gap-1 text-[10px]" style={{ color: '#34d399' }}>
                          <CheckCircle2 size={11} />已嵌入
                        </span>
                      ) : (
                        <span className="flex items-center gap-1 text-[10px]" style={{ color: '#f59e0b' }}>
                          <AlertTriangle size={11} />未嵌入
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Expanded content */}
                  {isExpanded && (
                    <div
                      className="px-4 pb-4 border-t flex flex-col gap-3"
                      style={{ borderColor: 'var(--color-border)' }}
                      onClick={e => e.stopPropagation()}
                    >
                      {isEditing ? (
                        <>
                          <input
                            className="w-full text-xs px-3 py-2 rounded-lg outline-none mt-3"
                            style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                            value={editDraft.title ?? doc.title}
                            onChange={e => setEditDraft(v => ({ ...v, title: e.target.value }))}
                          />
                          <textarea
                            rows={6}
                            className="w-full text-xs px-3 py-2 rounded-lg outline-none resize-y"
                            style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                            value={editDraft.content ?? doc.content ?? ''}
                            onChange={e => setEditDraft(v => ({ ...v, content: e.target.value }))}
                          />
                        </>
                      ) : (
                        <pre
                          className="text-xs leading-relaxed whitespace-pre-wrap mt-3 max-h-48 overflow-y-auto"
                          style={{ color: 'var(--color-muted)', fontFamily: 'inherit' }}
                        >
                          {doc.content || doc.preview}
                        </pre>
                      )}

                      <div className="flex items-center gap-2 justify-between">
                        <div className="flex items-center gap-2">
                          {isEditing ? (
                            <>
                              <button
                                onClick={() => handleSaveEdit(doc)}
                                className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg"
                                style={{ background: 'rgba(99,102,241,0.18)', color: '#818cf8' }}
                              >
                                <Save size={12} />保存
                              </button>
                              <button
                                onClick={() => { setEditingId(null); setEditDraft({}); }}
                                className="text-xs px-3 py-1.5 rounded-lg"
                                style={{ color: 'var(--color-muted)' }}
                              >
                                取消
                              </button>
                            </>
                          ) : (
                            <button
                              onClick={() => { setEditingId(doc.doc_id); setEditDraft({ title: doc.title, content: doc.content }); }}
                              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg"
                              style={{ background: 'rgba(255,255,255,0.05)', color: 'var(--color-muted)' }}
                            >
                              <Pencil size={12} />编辑
                            </button>
                          )}
                          <button
                            onClick={() => handleEmbedSingle(doc.doc_id)}
                            disabled={embeddingId === doc.doc_id}
                            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg"
                            style={{ background: 'rgba(99,102,241,0.1)', color: '#818cf8' }}
                          >
                            {embeddingId === doc.doc_id
                              ? <Loader2 size={12} className="animate-spin" />
                              : <RefreshCw size={12} />
                            }
                            重新嵌入
                          </button>
                        </div>
                        <button
                          onClick={() => handleDelete(doc.doc_id)}
                          className="flex items-center gap-1 text-xs px-2 py-1.5 rounded-lg transition-colors"
                          style={{ color: 'rgba(239,68,68,0.6)' }}
                        >
                          <Trash2 size={12} />
                        </button>
                      </div>

                      {isEditing && (
                        <p className="text-[10px]" style={{ color: '#f59e0b' }}>
                          保存后嵌入将失效，需重新嵌入
                        </p>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </SectionShell>
  );
}

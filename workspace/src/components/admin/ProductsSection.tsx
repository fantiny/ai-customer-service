import React, { useEffect, useState, useCallback } from 'react';
import {
  Plus, Pencil, Save, X, Loader2, Link, ExternalLink,
  CheckCircle2, XCircle, ChevronDown, ChevronRight, Tag,
} from 'lucide-react';
import { listProducts, updateProduct, createProduct } from '../../lib/adminApi';
import type { ProductInfo } from '../../types';
import SectionShell from './shared/SectionShell';

const STOCK_LABEL: Record<string, string> = { ready: '现货', custom: '定制' };

const STYLE_OPTIONS = [
  '鱼尾裙', '蓬蓬裙', 'A型裙', '轻纱款', '中式秀禾服', '简约款', '宫廷风', '仙女款',
];

interface EditState {
  name: string;
  style: string;
  price: string;
  deposit_rate: string;
  production_days: string;
  rush_available: boolean;
  stock_type: 'ready' | 'custom';
  colors: string;
  tags: string;
  occasions: string;
  description: string;
  active: boolean;
  purchase_url: string;
}

function productToEdit(p: ProductInfo): EditState {
  return {
    name: p.name,
    style: p.style,
    price: String(p.price),
    deposit_rate: String(p.deposit_rate),
    production_days: String(p.production_days),
    rush_available: p.rush_available,
    stock_type: p.stock_type,
    colors: p.colors.join('、'),
    tags: p.tags.join('、'),
    occasions: p.occasions.join('、'),
    description: p.description,
    active: p.active,
    purchase_url: p.purchase_url,
  };
}

function editToPayload(e: EditState) {
  return {
    name: e.name.trim(),
    style: e.style.trim(),
    price: parseFloat(e.price) || 0,
    deposit_rate: parseFloat(e.deposit_rate) || 0.3,
    production_days: parseInt(e.production_days) || 30,
    rush_available: e.rush_available,
    stock_type: e.stock_type,
    colors: e.colors.split(/[,、，]+/).map(s => s.trim()).filter(Boolean),
    tags: e.tags.split(/[,、，]+/).map(s => s.trim()).filter(Boolean),
    occasions: e.occasions.split(/[,、，]+/).map(s => s.trim()).filter(Boolean),
    description: e.description.trim(),
    active: e.active,
    purchase_url: e.purchase_url.trim(),
  };
}

const BLANK_EDIT: EditState = {
  name: '', style: '', price: '', deposit_rate: '0.30', production_days: '45',
  rush_available: false, stock_type: 'custom', colors: '', tags: '', occasions: '',
  description: '', active: true, purchase_url: '',
};

export default function ProductsSection() {
  const [products, setProducts] = useState<ProductInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState<EditState>(BLANK_EDIT);
  const [saving, setSaving] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [newDraft, setNewDraft] = useState<EditState & { product_id: string }>({ ...BLANK_EDIT, product_id: '' });
  const [savingNew, setSavingNew] = useState(false);
  const [toast, setToast] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try { setProducts(await listProducts()); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const showToast = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(''), 3000);
  };

  const handleSave = async (productId: string) => {
    setSaving(true);
    try {
      await updateProduct(productId, editToPayload(editDraft));
      setEditingId(null);
      await load();
      showToast('已保存');
    } finally {
      setSaving(false);
    }
  };

  const handleCreate = async () => {
    if (!newDraft.product_id.trim() || !newDraft.name.trim()) return;
    setSavingNew(true);
    try {
      await createProduct({ product_id: newDraft.product_id.trim(), ...editToPayload(newDraft) } as ProductInfo);
      setShowNew(false);
      setNewDraft({ ...BLANK_EDIT, product_id: '' });
      await load();
      showToast('商品已创建');
    } finally {
      setSavingNew(false);
    }
  };

  const urlCount = products.filter(p => p.purchase_url).length;

  const sectionContext = [
    `【商品管理】共 ${products.length} 件商品，${urlCount} 件已配置购买链接`,
    `现货：${products.filter(p => p.stock_type === 'ready').length}，定制：${products.filter(p => p.stock_type === 'custom').length}`,
    `下架：${products.filter(p => !p.active).length}`,
    urlCount < products.length
      ? `待配置购买链接：${products.filter(p => !p.purchase_url).map(p => p.name).slice(0, 5).join('、')}`
      : '全部商品已配置购买链接',
  ].join('\n');

  return (
    <SectionShell context={sectionContext}>
      <div className="flex flex-col gap-4">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-base font-bold" style={{ color: 'var(--color-text)' }}>商品管理</h2>
            <p className="text-xs mt-0.5" style={{ color: 'var(--color-muted)' }}>
              商品目录 · 购买链接 · 价格 · 定制周期
            </p>
          </div>
          <div className="flex items-center gap-2">
            {toast && (
              <span className="text-xs px-2 py-1 rounded" style={{ background: 'rgba(16,185,129,0.15)', color: '#34d399' }}>
                {toast}
              </span>
            )}
            {urlCount < products.length && (
              <span
                className="text-xs px-2 py-1 rounded flex items-center gap-1"
                style={{ background: 'rgba(245,158,11,0.12)', color: '#f59e0b', border: '1px solid rgba(245,158,11,0.2)' }}
              >
                <Link size={11} />
                {products.length - urlCount} 件未配置购买链接
              </span>
            )}
            <button
              onClick={() => setShowNew(v => !v)}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg transition-all"
              style={{ background: 'rgba(99,102,241,0.15)', color: '#818cf8', border: '1px solid rgba(99,102,241,0.25)' }}
            >
              <Plus size={12} />
              新建商品
            </button>
          </div>
        </div>

        {/* New product form */}
        {showNew && (
          <ProductForm
            draft={{ ...newDraft }}
            onDraftChange={d => setNewDraft(prev => ({ ...prev, ...d }))}
            productId={newDraft.product_id}
            onProductIdChange={v => setNewDraft(prev => ({ ...prev, product_id: v }))}
            showProductId
            onSave={handleCreate}
            onCancel={() => setShowNew(false)}
            saving={savingNew}
            canSave={!!newDraft.product_id.trim() && !!newDraft.name.trim()}
          />
        )}

        {/* Product list */}
        {loading ? (
          <div className="flex items-center gap-2 text-xs py-4" style={{ color: 'var(--color-muted)' }}>
            <Loader2 size={14} className="animate-spin" /> 加载中…
          </div>
        ) : (
          <div className="flex flex-col gap-1.5">
            {products.map(p => {
              const isExpanded = expandedId === p.product_id;
              const isEditing = editingId === p.product_id;
              return (
                <div
                  key={p.product_id}
                  className="rounded-xl overflow-hidden"
                  style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)', opacity: p.active ? 1 : 0.55 }}
                >
                  {/* Row header */}
                  <div
                    className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-white/[0.02] transition-colors"
                    onClick={() => setExpandedId(isExpanded ? null : p.product_id)}
                  >
                    <span style={{ color: 'var(--color-muted)', opacity: 0.5 }}>
                      {isExpanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                    </span>

                    {/* Product ID badge */}
                    <code
                      className="text-[10px] px-1.5 py-0.5 rounded font-mono flex-shrink-0"
                      style={{ background: 'rgba(99,102,241,0.12)', color: '#818cf8' }}
                    >
                      {p.product_id}
                    </code>

                    {/* Name + style */}
                    <span className="text-xs font-medium flex-1 truncate" style={{ color: 'var(--color-text)' }}>
                      {p.name}
                    </span>
                    <span className="text-[11px] hidden md:block" style={{ color: 'var(--color-muted)' }}>
                      {p.style}
                    </span>

                    {/* Price */}
                    <span className="text-xs font-mono font-semibold flex-shrink-0" style={{ color: '#10b981' }}>
                      ¥{p.price.toLocaleString()}
                    </span>

                    {/* Stock badge */}
                    <span
                      className="text-[10px] px-1.5 py-0.5 rounded flex-shrink-0"
                      style={{
                        background: p.stock_type === 'ready' ? 'rgba(16,185,129,0.12)' : 'rgba(6,182,212,0.1)',
                        color: p.stock_type === 'ready' ? '#10b981' : '#06b6d4',
                      }}
                    >
                      {STOCK_LABEL[p.stock_type]}
                    </span>

                    {/* URL status */}
                    {p.purchase_url ? (
                      <span className="flex-shrink-0" style={{ color: '#10b981' }} title={p.purchase_url}>
                        <Link size={13} />
                      </span>
                    ) : (
                      <span className="flex-shrink-0" style={{ color: '#f59e0b' }} title="未配置购买链接">
                        <Link size={13} />
                      </span>
                    )}

                    {/* Active status */}
                    {!p.active && (
                      <span className="text-[10px] flex-shrink-0" style={{ color: '#ef4444' }}>已下架</span>
                    )}
                  </div>

                  {/* Expanded content */}
                  {isExpanded && (
                    <div
                      className="px-4 pb-4 border-t"
                      style={{ borderColor: 'var(--color-border)' }}
                      onClick={e => e.stopPropagation()}
                    >
                      {isEditing ? (
                        <ProductForm
                          draft={editDraft}
                          onDraftChange={d => setEditDraft(prev => ({ ...prev, ...d }))}
                          onSave={() => handleSave(p.product_id)}
                          onCancel={() => { setEditingId(null); }}
                          saving={saving}
                          canSave={!!editDraft.name.trim()}
                          compact
                        />
                      ) : (
                        <div className="mt-3 flex flex-col gap-2">
                          {/* Purchase URL — most important field, shown prominently */}
                          <div
                            className="flex items-center gap-2 px-3 py-2 rounded-lg"
                            style={{
                              background: p.purchase_url ? 'rgba(16,185,129,0.06)' : 'rgba(245,158,11,0.06)',
                              border: `1px solid ${p.purchase_url ? 'rgba(16,185,129,0.2)' : 'rgba(245,158,11,0.2)'}`,
                            }}
                          >
                            <Link size={13} style={{ color: p.purchase_url ? '#10b981' : '#f59e0b', flexShrink: 0 }} />
                            {p.purchase_url ? (
                              <a
                                href={p.purchase_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-xs flex items-center gap-1 hover:underline truncate"
                                style={{ color: '#34d399' }}
                                onClick={e => e.stopPropagation()}
                              >
                                {p.purchase_url}
                                <ExternalLink size={10} className="flex-shrink-0" />
                              </a>
                            ) : (
                              <span className="text-xs" style={{ color: '#f59e0b' }}>未配置购买链接</span>
                            )}
                          </div>

                          <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-xs">
                            <InfoRow label="定金比例" value={`${Math.round(p.deposit_rate * 100)}%`} />
                            <InfoRow label="生产周期" value={`${p.production_days} 天`} />
                            <InfoRow label="加急" value={p.rush_available ? '支持' : '不支持'} />
                            <InfoRow label="可选颜色" value={p.colors.join('、') || '—'} />
                            <InfoRow label="适合场合" value={p.occasions.join('、') || '—'} />
                            <InfoRow label="标签" value={p.tags.join('、') || '—'} />
                          </div>
                          {p.description && (
                            <p className="text-xs mt-1" style={{ color: 'var(--color-muted)' }}>{p.description}</p>
                          )}

                          <div className="flex justify-end mt-1">
                            <button
                              onClick={() => { setEditingId(p.product_id); setEditDraft(productToEdit(p)); }}
                              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg"
                              style={{ background: 'rgba(255,255,255,0.05)', color: 'var(--color-muted)' }}
                            >
                              <Pencil size={12} /> 编辑
                            </button>
                          </div>
                        </div>
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

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span style={{ color: 'var(--color-muted)' }}>{label}：</span>
      <span style={{ color: 'var(--color-text)' }}>{value}</span>
    </div>
  );
}

interface FormProps {
  draft: EditState;
  onDraftChange: (partial: Partial<EditState>) => void;
  productId?: string;
  onProductIdChange?: (v: string) => void;
  showProductId?: boolean;
  onSave: () => void;
  onCancel: () => void;
  saving: boolean;
  canSave: boolean;
  compact?: boolean;
}

function ProductForm({
  draft, onDraftChange, productId, onProductIdChange, showProductId,
  onSave, onCancel, saving, canSave, compact,
}: FormProps) {
  const inputCls = "w-full text-xs px-3 py-2 rounded-lg outline-none";
  const inputStyle = {
    background: 'rgba(255,255,255,0.05)',
    border: '1px solid var(--color-border)',
    color: 'var(--color-text)',
  };

  return (
    <div
      className={`flex flex-col gap-3 ${compact ? 'mt-3' : 'rounded-xl p-4'}`}
      style={compact ? {} : { background: 'var(--color-surface)', border: '1px solid rgba(99,102,241,0.3)' }}
    >
      {!compact && (
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold" style={{ color: '#818cf8' }}>新建商品</span>
          <button onClick={onCancel} style={{ color: 'var(--color-muted)' }}><X size={14} /></button>
        </div>
      )}

      {/* Purchase URL — top priority */}
      <div>
        <label className="text-[10px] font-semibold mb-1 block" style={{ color: '#10b981' }}>
          购买链接（店铺官方链接）
        </label>
        <div className="flex items-center gap-2">
          <Link size={13} className="flex-shrink-0" style={{ color: '#10b981' }} />
          <input
            className={inputCls}
            style={{ ...inputStyle, border: '1px solid rgba(16,185,129,0.3)' }}
            placeholder="https://your-store.com/product/..."
            value={draft.purchase_url}
            onChange={e => onDraftChange({ purchase_url: e.target.value })}
          />
        </div>
      </div>

      {/* Core fields */}
      <div className="grid grid-cols-2 gap-2">
        {showProductId && (
          <div className="col-span-2">
            <label className="text-[10px] mb-1 block" style={{ color: 'var(--color-muted)' }}>商品编号</label>
            <input
              className={`${inputCls} font-mono`}
              style={inputStyle}
              placeholder="如 WD-P016"
              value={productId ?? ''}
              onChange={e => onProductIdChange?.(e.target.value)}
            />
          </div>
        )}
        <div>
          <label className="text-[10px] mb-1 block" style={{ color: 'var(--color-muted)' }}>商品名称</label>
          <input className={inputCls} style={inputStyle} value={draft.name} onChange={e => onDraftChange({ name: e.target.value })} placeholder="御风宫廷风" />
        </div>
        <div>
          <label className="text-[10px] mb-1 block" style={{ color: 'var(--color-muted)' }}>款式</label>
          <select className={inputCls} style={inputStyle} value={draft.style} onChange={e => onDraftChange({ style: e.target.value })}>
            <option value="">选择款式</option>
            {STYLE_OPTIONS.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        <div>
          <label className="text-[10px] mb-1 block" style={{ color: 'var(--color-muted)' }}>价格 (元)</label>
          <input className={`${inputCls} font-mono`} style={inputStyle} value={draft.price} onChange={e => onDraftChange({ price: e.target.value })} placeholder="8900" type="number" />
        </div>
        <div>
          <label className="text-[10px] mb-1 block" style={{ color: 'var(--color-muted)' }}>定金比例</label>
          <input className={`${inputCls} font-mono`} style={inputStyle} value={draft.deposit_rate} onChange={e => onDraftChange({ deposit_rate: e.target.value })} placeholder="0.30" type="number" step="0.01" />
        </div>
        <div>
          <label className="text-[10px] mb-1 block" style={{ color: 'var(--color-muted)' }}>生产周期 (天)</label>
          <input className={`${inputCls} font-mono`} style={inputStyle} value={draft.production_days} onChange={e => onDraftChange({ production_days: e.target.value })} type="number" />
        </div>
        <div>
          <label className="text-[10px] mb-1 block" style={{ color: 'var(--color-muted)' }}>库存类型</label>
          <select className={inputCls} style={inputStyle} value={draft.stock_type} onChange={e => onDraftChange({ stock_type: e.target.value as 'ready' | 'custom' })}>
            <option value="custom">定制款</option>
            <option value="ready">现货</option>
          </select>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="text-[10px] mb-1 block" style={{ color: 'var(--color-muted)' }}>可选颜色（逗号分隔）</label>
          <input className={inputCls} style={inputStyle} value={draft.colors} onChange={e => onDraftChange({ colors: e.target.value })} placeholder="象牙白、香槟金、裸粉" />
        </div>
        <div>
          <label className="text-[10px] mb-1 block" style={{ color: 'var(--color-muted)' }}>适合场合（逗号分隔）</label>
          <input className={inputCls} style={inputStyle} value={draft.occasions} onChange={e => onDraftChange({ occasions: e.target.value })} placeholder="中式婚礼、草坪婚礼" />
        </div>
        <div>
          <label className="text-[10px] mb-1 block" style={{ color: 'var(--color-muted)' }}>标签（逗号分隔）</label>
          <input className={inputCls} style={inputStyle} value={draft.tags} onChange={e => onDraftChange({ tags: e.target.value })} placeholder="宫廷风、新中式" />
        </div>
        <div className="flex items-center gap-4 pt-4">
          <label className="flex items-center gap-2 text-xs cursor-pointer" style={{ color: 'var(--color-muted)' }}>
            <input type="checkbox" checked={draft.rush_available} onChange={e => onDraftChange({ rush_available: e.target.checked })} />
            支持加急
          </label>
          <label className="flex items-center gap-2 text-xs cursor-pointer" style={{ color: 'var(--color-muted)' }}>
            <input type="checkbox" checked={draft.active} onChange={e => onDraftChange({ active: e.target.checked })} />
            上架
          </label>
        </div>
      </div>

      <div>
        <label className="text-[10px] mb-1 block" style={{ color: 'var(--color-muted)' }}>商品描述</label>
        <textarea
          rows={3}
          className={`${inputCls} resize-y`}
          style={inputStyle}
          value={draft.description}
          onChange={e => onDraftChange({ description: e.target.value })}
          placeholder="描述商品特点、面料、工艺…"
        />
      </div>

      <div className="flex justify-end gap-2">
        <button onClick={onCancel} className="text-xs px-3 py-1.5 rounded-lg" style={{ color: 'var(--color-muted)' }}>取消</button>
        <button
          onClick={onSave}
          disabled={saving || !canSave}
          className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg"
          style={{
            background: 'rgba(99,102,241,0.2)', color: '#818cf8',
            border: '1px solid rgba(99,102,241,0.3)',
            opacity: saving || !canSave ? 0.5 : 1,
          }}
        >
          {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
          保存
        </button>
      </div>
    </div>
  );
}

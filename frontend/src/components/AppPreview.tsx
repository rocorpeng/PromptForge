import {
  Check,
  ChevronDown,
  Copy,
  ExternalLink,
  Grid2X2,
  LayoutList,
  LoaderCircle,
  Plus,
  Search,
  Send,
  X,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { api } from '../lib/api';
import type {
  AppField,
  AppSpec,
  Identifier,
  RecordItem,
} from '../types/promptforge';
import { DynamicField, RecordActions } from './RecordControls';

interface AppPreviewProps {
  projectId: Identifier;
  spec: AppSpec;
  initialRecords?: RecordItem[];
  publicMode?: boolean;
  publishing?: boolean;
  publicUrl?: string;
  onPublish?: () => Promise<void>;
}

type FormValues = Record<string, unknown>;

const HIGHLIGHT_COLORS = ['green', 'red', 'amber', 'blue', 'gray'];

const emptyValues = (fields: AppField[]): FormValues =>
  Object.fromEntries(
    fields.map(field => [
      field.key,
      field.type === 'boolean' ? false : field.type === 'number' ? '' : '',
    ]),
  );

const valueText = (value: unknown) => {
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (value === null || value === undefined || value === '') return '—';
  return String(value);
};

export function AppPreview({
  projectId,
  spec,
  initialRecords,
  publicMode = false,
  publishing,
  publicUrl,
  onPublish,
}: AppPreviewProps) {
  const [records, setRecords] = useState<RecordItem[]>(initialRecords ?? []);
  const [loading, setLoading] = useState(!initialRecords);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('');
  const [editing, setEditing] = useState<RecordItem | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [values, setValues] = useState<FormValues>(() =>
    emptyValues(spec.entity.fields),
  );
  const [saving, setSaving] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    setValues(emptyValues(spec.entity.fields));
  }, [spec]);

  useEffect(() => {
    if (initialRecords) {
      setRecords(initialRecords);
      setLoading(false);
      return;
    }
    let active = true;
    setLoading(true);
    api
      .listRecords(projectId)
      .then(items => {
        if (active) setRecords(items);
      })
      .catch((reason: Error) => {
        if (active) setError(reason.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [projectId, initialRecords]);

  const visibleFields = spec.view.visibleFields
    .map(key => spec.entity.fields.find(field => field.key === key))
    .filter((field): field is AppField => Boolean(field));
  const filterField = spec.entity.fields.find(
    field => field.key === spec.features.filterField,
  );

  const filteredRecords = useMemo(() => {
    const term = search.trim().toLocaleLowerCase();
    return records.filter(record => {
      const matchesSearch =
        !term ||
        Object.values(record.data).some(value =>
          valueText(value).toLocaleLowerCase().includes(term),
        );
      const matchesFilter =
        !filter || record.data[spec.features.filterField ?? ''] === filter;
      return matchesSearch && matchesFilter;
    });
  }, [records, search, filter, spec.features.filterField]);

  const openCreate = () => {
    setEditing(null);
    setValues(emptyValues(spec.entity.fields));
    setFormOpen(true);
  };

  const openEdit = (record: RecordItem) => {
    setEditing(record);
    setValues({ ...emptyValues(spec.entity.fields), ...record.data });
    setFormOpen(true);
  };

  const submitRecord = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError('');
    const payload = Object.fromEntries(
      spec.entity.fields.map(field => {
        const value = values[field.key];
        if (field.type === 'number') {
          return [field.key, value === '' ? null : Number(value)];
        }
        return [field.key, value];
      }),
    );
    try {
      if (editing) {
        const updated = await api.updateRecord(projectId, editing.id, payload);
        setRecords(current =>
          current.map(item => (item.id === updated.id ? updated : item)),
        );
      } else {
        const created = await api.createRecord(projectId, payload);
        setRecords(current => [created, ...current]);
      }
      setFormOpen(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const removeRecord = async (record: RecordItem) => {
    if (!window.confirm(`确定删除这条${spec.entity.name}吗？`)) return;
    try {
      await api.deleteRecord(projectId, record.id);
      setRecords(current => current.filter(item => item.id !== record.id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '删除失败');
    }
  };

  const copyUrl = async () => {
    if (!publicUrl) return;
    await navigator.clipboard.writeText(publicUrl);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  };

  const renderValue = (field: AppField, value: unknown) => {
    if (field.type === 'boolean') {
      return (
        <span className={`boolean-value ${value ? 'yes' : 'no'}`}>
          <span /> {value ? '是' : '否'}
        </span>
      );
    }
    if (field.type === 'select' && value) {
      return <span className="value-pill">{String(value)}</span>;
    }
    return valueText(value);
  };

  const colorRule = spec.view.colorRule;
  const isHighlighted = (record: RecordItem) =>
    colorRule && record.data[colorRule.field] === colorRule.value;
  // colorRule.color 之前被忽略，高亮色写死在 CSS 里；这里把它落到具体类名上。
  const highlightClass = (record: RecordItem) => {
    if (!colorRule || !isHighlighted(record)) return '';
    const color = String(colorRule.color ?? '');
    const safe = HIGHLIGHT_COLORS.includes(color) ? color : 'green';
    return `highlighted highlight-${safe}`;
  };

  return (
    <div
      className={`app-preview ${publicMode ? 'public-app' : ''}`}
      style={{ '--app-accent': spec.app.primaryColor } as React.CSSProperties}
    >
      {!publicMode && (
        <div className="preview-chrome">
          <div>
            <span className="chrome-dot red" />
            <span className="chrome-dot amber" />
            <span className="chrome-dot green" />
          </div>
          <span>交互预览</span>
          <div className="preview-tools">
            {publicUrl && (
              <button className="copy-link" type="button" onClick={copyUrl}>
                {copied ? <Check size={13} /> : <Copy size={13} />}
                {copied ? '已复制' : '公开链接'}
              </button>
            )}
            <button
              className="publish-button"
              disabled={publishing}
              type="button"
              onClick={onPublish}
            >
              {publishing ? (
                <LoaderCircle className="spin" size={14} />
              ) : (
                <Send size={14} />
              )}
              {publishing ? '发布中' : '发布'}
            </button>
          </div>
        </div>
      )}

      <div className="generated-app-shell">
        <header className="generated-header">
          <div className="generated-brand">
            <span>{spec.app.name.slice(0, 1)}</span>
            <div>
              <strong>{spec.app.name}</strong>
              <small>{spec.app.description}</small>
            </div>
          </div>
          {publicMode && (
            <span className="powered-badge">
              <ExternalLink size={12} /> PromptForge
            </span>
          )}
        </header>

        <main className="generated-content">
          <div className="app-title-row">
            <div>
              <span className="record-kicker">
                WORKSPACE / {spec.entity.namePlural}
              </span>
              <h1>{spec.entity.namePlural}</h1>
              <p>
                共 {filteredRecords.length} 条{spec.entity.name}
              </p>
            </div>
            {spec.features.create && (
              <button
                className="app-primary-button"
                type="button"
                onClick={openCreate}
              >
                <Plus size={16} />
                新增{spec.entity.name}
              </button>
            )}
          </div>

          {(spec.features.search || filterField) && (
            <div className="data-toolbar">
              {spec.features.search && (
                <label className="search-control">
                  <Search size={16} />
                  <input
                    placeholder={`搜索${spec.entity.name}…`}
                    value={search}
                    onChange={event => setSearch(event.target.value)}
                  />
                </label>
              )}
              {filterField && (
                <label className="filter-control">
                  <select
                    value={filter}
                    onChange={event => setFilter(event.target.value)}
                  >
                    <option value="">全部{filterField.label}</option>
                    {filterField.options?.map(option => (
                      <option key={option}>{option}</option>
                    ))}
                  </select>
                  <ChevronDown size={15} />
                </label>
              )}
              <span className="layout-indicator">
                {spec.view.layout === 'cards' ? (
                  <Grid2X2 size={15} />
                ) : (
                  <LayoutList size={15} />
                )}
              </span>
            </div>
          )}

          {error && (
            <div className="inline-error">
              <X size={15} />
              {error}
              <button type="button" onClick={() => setError('')}>
                关闭
              </button>
            </div>
          )}

          {loading ? (
            <div className="records-loading">
              <LoaderCircle className="spin" />
              正在读取数据…
            </div>
          ) : filteredRecords.length === 0 ? (
            <div className="records-empty">
              <span>
                <LayoutList size={24} />
              </span>
              <h3>暂无{spec.entity.name}</h3>
              <p>
                {search || filter
                  ? '没有符合当前条件的数据。'
                  : '新增第一条数据，让应用运转起来。'}
              </p>
              {spec.features.create && !search && !filter && (
                <button type="button" onClick={openCreate}>
                  <Plus size={14} />
                  立即新增
                </button>
              )}
            </div>
          ) : spec.view.layout === 'cards' ? (
            <div className="record-grid">
              {filteredRecords.map(record => (
                <article
                  className={`record-card ${highlightClass(record)}`}
                  key={record.id}
                >
                  <div className="record-card-head">
                    <strong>
                      {valueText(record.data[spec.view.titleField])}
                    </strong>
                    <RecordActions
                      spec={spec}
                      record={record}
                      onEdit={openEdit}
                      onDelete={removeRecord}
                    />
                  </div>
                  <dl>
                    {visibleFields
                      .filter(field => field.key !== spec.view.titleField)
                      .map(field => (
                        <div key={field.key}>
                          <dt>{field.label}</dt>
                          <dd>{renderValue(field, record.data[field.key])}</dd>
                        </div>
                      ))}
                  </dl>
                </article>
              ))}
            </div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    {visibleFields.map(field => (
                      <th key={field.key}>{field.label}</th>
                    ))}
                    {(spec.features.edit || spec.features.delete) && (
                      <th>操作</th>
                    )}
                  </tr>
                </thead>
                <tbody>
                  {filteredRecords.map(record => (
                    <tr
                      className={highlightClass(record)}
                      key={record.id}
                    >
                      {visibleFields.map(field => (
                        <td key={field.key}>
                          {renderValue(field, record.data[field.key])}
                        </td>
                      ))}
                      {(spec.features.edit || spec.features.delete) && (
                        <td>
                          <RecordActions
                            spec={spec}
                            record={record}
                            onEdit={openEdit}
                            onDelete={removeRecord}
                          />
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </main>
      </div>

      {formOpen && (
        <div className="app-modal-backdrop" role="presentation">
          <form className="record-dialog" onSubmit={submitRecord}>
            <div className="record-dialog-head">
              <div>
                <span>{editing ? 'EDIT RECORD' : 'NEW RECORD'}</span>
                <h2>
                  {editing
                    ? `编辑${spec.entity.name}`
                    : `新增${spec.entity.name}`}
                </h2>
              </div>
              <button
                aria-label="关闭"
                type="button"
                onClick={() => setFormOpen(false)}
              >
                <X size={18} />
              </button>
            </div>
            <div className="dynamic-form">
              {spec.entity.fields.map(field => (
                <DynamicField
                  field={field}
                  key={field.key}
                  value={values[field.key]}
                  onChange={value =>
                    setValues(current => ({ ...current, [field.key]: value }))
                  }
                />
              ))}
            </div>
            <div className="record-dialog-actions">
              <button type="button" onClick={() => setFormOpen(false)}>
                取消
              </button>
              <button
                className="app-primary-button"
                disabled={saving}
                type="submit"
              >
                {saving ? (
                  <LoaderCircle className="spin" size={15} />
                ) : (
                  <Check size={15} />
                )}
                {saving ? '保存中' : '保存记录'}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}

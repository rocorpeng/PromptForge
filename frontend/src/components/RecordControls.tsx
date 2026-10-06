import { Edit3, Trash2 } from 'lucide-react';
import type { AppField, AppSpec, RecordItem } from '../types/promptforge';

interface ActionProps {
  spec: AppSpec;
  record: RecordItem;
  onEdit: (record: RecordItem) => void;
  onDelete: (record: RecordItem) => void;
}

export function RecordActions({ spec, record, onEdit, onDelete }: ActionProps) {
  return (
    <div className="record-actions">
      {spec.features.edit && (
        <button aria-label="编辑" type="button" onClick={() => onEdit(record)}>
          <Edit3 size={14} />
        </button>
      )}
      {spec.features.delete && (
        <button
          aria-label="删除"
          className="danger"
          type="button"
          onClick={() => onDelete(record)}
        >
          <Trash2 size={14} />
        </button>
      )}
    </div>
  );
}

interface FieldProps {
  field: AppField;
  value: unknown;
  onChange: (value: unknown) => void;
}

export function DynamicField({ field, value, onChange }: FieldProps) {
  const inputId = `record-field-${field.key}`;
  if (field.type === 'boolean') {
    return (
      <label className="toggle-field" htmlFor={inputId}>
        <span>
          <strong>{field.label}</strong>
          <small>启用此选项</small>
        </span>
        <input
          checked={Boolean(value)}
          id={inputId}
          type="checkbox"
          onChange={event => onChange(event.target.checked)}
        />
        <i />
      </label>
    );
  }
  return (
    <label
      className={`form-field ${field.type === 'textarea' ? 'wide' : ''}`}
      htmlFor={inputId}
    >
      <span>
        {field.label}
        {field.required && <em>*</em>}
      </span>
      {field.type === 'textarea' ? (
        <textarea
          id={inputId}
          required={field.required}
          rows={3}
          value={String(value ?? '')}
          onChange={event => onChange(event.target.value)}
        />
      ) : field.type === 'select' ? (
        <select
          id={inputId}
          required={field.required}
          value={String(value ?? '')}
          onChange={event => onChange(event.target.value)}
        >
          <option value="">请选择</option>
          {field.options?.map(option => (
            <option key={option}>{option}</option>
          ))}
        </select>
      ) : (
        <input
          id={inputId}
          required={field.required}
          type={field.type}
          value={String(value ?? '')}
          onChange={event => onChange(event.target.value)}
        />
      )}
    </label>
  );
}

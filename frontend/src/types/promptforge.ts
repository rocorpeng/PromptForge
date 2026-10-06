export type Identifier = number | string;

export type FieldType =
  | 'text'
  | 'textarea'
  | 'number'
  | 'date'
  | 'select'
  | 'boolean';

export interface AppField {
  key: string;
  label: string;
  type: FieldType;
  required?: boolean;
  options?: string[];
}

export interface ColorRule {
  field: string;
  operator?: string;
  value: unknown;
  color?: string;
}

export interface AppSpec {
  app: { name: string; description: string; primaryColor: string };
  entity: { name: string; namePlural: string; fields: AppField[] };
  features: {
    create: boolean;
    edit: boolean;
    delete: boolean;
    search: boolean;
    filterField?: string;
  };
  view: {
    layout: 'table' | 'cards';
    titleField: string;
    visibleFields: string[];
    colorRule?: ColorRule;
  };
}

export interface RawAppSpec {
  app?: Partial<AppSpec['app']>;
  entity?: Partial<AppSpec['entity']>;
  features?: Partial<AppSpec['features']> & { filter?: boolean };
  view?: Partial<AppSpec['view']>;
  title?: string;
  description?: string;
  entityName?: string;
  fields?: AppField[];
  layout?: 'table' | 'cards';
  colorRule?: ColorRule;
}

export interface Project {
  id: Identifier;
  name: string;
  description?: string | null;
  slug?: string | null;
  version_count?: number;
  record_count?: number;
  latest_version_number?: number | null;
}

export interface Message {
  id: Identifier;
  role: 'user' | 'team_lead' | 'engineer' | string;
  content: string;
  created_at?: string;
}

export interface Version {
  id: Identifier;
  version_number: number;
  app_spec: RawAppSpec;
  source_prompt?: string | null;
  created_at?: string;
  restored_from_version_id?: Identifier | null;
}

export interface AgentStep {
  agent: string;
  status: 'pending' | 'running' | 'completed' | string;
  summary: string;
}

export interface RecordItem {
  id: Identifier;
  project_id?: Identifier;
  data: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
}

export const normalizeSpec = (raw?: RawAppSpec | null): AppSpec | null => {
  if (!raw) return null;
  const fields = raw.entity?.fields ?? raw.fields ?? [];
  const titleField = raw.view?.titleField ?? fields[0]?.key ?? 'id';
  const filterField =
    raw.features?.filterField ??
    (raw.features?.filter
      ? fields.find(field => field.type === 'select')?.key
      : undefined);

  return {
    app: {
      name: raw.app?.name ?? raw.title ?? '未命名应用',
      description: raw.app?.description ?? raw.description ?? '',
      primaryColor: raw.app?.primaryColor ?? '#087f78',
    },
    entity: {
      name: raw.entity?.name ?? raw.entityName ?? '记录',
      namePlural:
        raw.entity?.namePlural ??
        `${raw.entity?.name ?? raw.entityName ?? '记录'}列表`,
      fields,
    },
    features: {
      create: raw.features?.create ?? true,
      edit: raw.features?.edit ?? true,
      delete: raw.features?.delete ?? true,
      search: raw.features?.search ?? false,
      filterField,
    },
    view: {
      layout: raw.view?.layout ?? raw.layout ?? 'table',
      titleField,
      visibleFields: raw.view?.visibleFields ?? fields.map(field => field.key),
      colorRule: raw.view?.colorRule ?? raw.colorRule,
    },
  };
};

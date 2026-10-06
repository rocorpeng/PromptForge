import type {
  AgentStep,
  Identifier,
  Message,
  Project,
  RawAppSpec,
  RecordItem,
  Version,
} from '../types/promptforge';

export const API_BASE =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') || 'http://localhost:8000';

type JsonObject = Record<string, unknown>;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  });

  if (!response.ok) {
    let message = `请求失败 (${response.status})`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) message = body.detail;
    } catch {
      // 保留通用错误信息。
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export const api = {
  async listProjects() {
    const data = await request<{ projects: Project[] }>('/api/projects');
    return data.projects;
  },
  async createProject(name: string, description?: string) {
    const data = await request<{ project: Project }>('/api/projects', {
      method: 'POST',
      body: JSON.stringify({ name, description: description || undefined }),
    });
    return data.project;
  },
  getProject(id: Identifier) {
    return request<{
      project: Project;
      messages: Message[];
      versions: Version[];
    }>(`/api/projects/${id}`);
  },
  generate(id: Identifier, prompt: string) {
    return request<{
      steps: AgentStep[];
      messages: Message[];
      version: Version;
      /** 实际使用的生成器：deepseek 为模型生成，local 为本地规则回退 */
      engine?: 'deepseek' | 'local';
      /** engine 为 local 时的回退原因 */
      fallback_reason?: string | null;
    }>(`/api/projects/${id}/generate`, {
      method: 'POST',
      body: JSON.stringify({ prompt }),
    });
  },
  async listVersions(id: Identifier) {
    const data = await request<{ versions: Version[] }>(
      `/api/projects/${id}/versions`,
    );
    return data.versions;
  },
  async restoreVersion(projectId: Identifier, versionId: Identifier) {
    const data = await request<{ version: Version }>(
      `/api/projects/${projectId}/versions/${versionId}/restore`,
      { method: 'POST' },
    );
    return data.version;
  },
  publish(id: Identifier) {
    return request<{ slug: string; project: Project; version: Version }>(
      `/api/projects/${id}/publish`,
      { method: 'POST' },
    );
  },
  getPublic(slug: string) {
    return request<{
      project: Project;
      version: Version;
      app_spec: RawAppSpec;
      records: RecordItem[];
    }>(`/api/public/${encodeURIComponent(slug)}`);
  },
  async listRecords(id: Identifier) {
    const data = await request<{ records: RecordItem[] }>(
      `/api/projects/${id}/records`,
    );
    return data.records;
  },
  async createRecord(id: Identifier, values: JsonObject) {
    const data = await request<{ record: RecordItem }>(
      `/api/projects/${id}/records`,
      { method: 'POST', body: JSON.stringify(values) },
    );
    return data.record;
  },
  async updateRecord(
    projectId: Identifier,
    recordId: Identifier,
    values: JsonObject,
  ) {
    const data = await request<{ record: RecordItem }>(
      `/api/projects/${projectId}/records/${recordId}`,
      { method: 'PATCH', body: JSON.stringify(values) },
    );
    return data.record;
  },
  deleteRecord(projectId: Identifier, recordId: Identifier) {
    return request<JsonObject>(
      `/api/projects/${projectId}/records/${recordId}`,
      { method: 'DELETE' },
    );
  },
};

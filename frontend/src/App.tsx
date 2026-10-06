import {
  Bot,
  CheckCircle2,
  Database,
  Eye,
  FolderKanban,
  LoaderCircle,
  MessageSquareText,
  RefreshCw,
  WifiOff,
} from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { AppPreview } from './components/AppPreview';
import { EmptyPreview } from './components/EmptyPreview';
import { ProjectSidebar } from './components/ProjectSidebar';
import { StudioPanel } from './components/StudioPanel';
import { api } from './lib/api';
import {
  type AgentStep,
  type AppSpec,
  type Message,
  type Project,
  type RecordItem,
  type Version,
  normalizeSpec,
} from './types/promptforge';

type MobilePanel = 'projects' | 'studio' | 'preview';

const runningSteps: AgentStep[] = [
  { agent: 'team_lead', status: 'running', summary: '理解需求并规划数据模型' },
  { agent: 'engineer', status: 'pending', summary: '生成界面与交互能力' },
  { agent: 'engineer', status: 'pending', summary: '验证 AppSpec 并创建版本' },
];

const Page = () => {
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [versions, setVersions] = useState<Version[]>([]);
  const [steps, setSteps] = useState<AgentStep[]>([]);
  const [spec, setSpec] = useState<AppSpec | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [restoringId, setRestoringId] = useState<Version['id']>();
  const [publicUrl, setPublicUrl] = useState('');
  const [error, setError] = useState('');
  const [mobilePanel, setMobilePanel] = useState<MobilePanel>('studio');
  const [publicMode, setPublicMode] = useState(false);
  const [publicRecords, setPublicRecords] = useState<RecordItem[]>();

  const loadProject = useCallback(async (selected: Project) => {
    setProject(selected);
    setError('');
    setMobilePanel('studio');
    try {
      const detail = await api.getProject(selected.id);
      setProject(detail.project);
      setMessages(detail.messages);
      setVersions(detail.versions);
      setSpec(normalizeSpec(detail.versions[0]?.app_spec));
      if (detail.project.slug) {
        const url = new URL(window.location.href);
        url.search = '';
        url.searchParams.set('public', detail.project.slug);
        setPublicUrl(url.toString());
      } else {
        setPublicUrl('');
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '项目加载失败');
    }
  }, []);

  useEffect(() => {
    const slug = new URLSearchParams(window.location.search).get('public');
    if (slug) {
      setPublicMode(true);
      api
        .getPublic(slug)
        .then(data => {
          setProject(data.project);
          setSpec(normalizeSpec(data.app_spec));
          setPublicRecords(data.records);
        })
        .catch((reason: Error) => setError(reason.message))
        .finally(() => setLoading(false));
      return;
    }

    api
      .listProjects()
      .then(items => {
        setProjects(items);
        if (items[0]) return loadProject(items[0]);
      })
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false));
  }, [loadProject]);

  const createProject = async (name: string, description: string) => {
    try {
      const created = await api.createProject(name, description);
      setProjects(current => [created, ...current]);
      await loadProject(created);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '创建失败');
      throw reason;
    }
  };

  const generate = async (prompt: string) => {
    if (!project) return;
    setGenerating(true);
    setError('');
    setSteps(runningSteps);
    const temporaryId = `pending-${Date.now()}`;
    setMessages(current => [
      ...current,
      { id: temporaryId, role: 'user', content: prompt },
    ]);
    try {
      const result = await api.generate(project.id, prompt);
      setSteps(result.steps);
      setMessages(current => [
        ...current.filter(message => message.id !== temporaryId),
        ...result.messages,
      ]);
      setVersions(current => [
        result.version,
        ...current.filter(version => version.id !== result.version.id),
      ]);
      setSpec(normalizeSpec(result.version.app_spec));
      setProjects(current =>
        current.map(item =>
          item.id === project.id
            ? {
                ...item,
                latest_version_number: result.version.version_number,
                version_count: (item.version_count ?? 0) + 1,
              }
            : item,
        ),
      );
      setMobilePanel('preview');
    } catch (reason) {
      setMessages(current =>
        current.filter(message => message.id !== temporaryId),
      );
      setSteps([]);
      setError(reason instanceof Error ? reason.message : '生成失败');
    } finally {
      setGenerating(false);
    }
  };

  const restore = async (version: Version) => {
    if (!project) return;
    setRestoringId(version.id);
    setError('');
    try {
      const restored = await api.restoreVersion(project.id, version.id);
      setVersions(current => [restored, ...current]);
      setSpec(normalizeSpec(restored.app_spec));
      setSteps([
        {
          agent: 'engineer',
          status: 'completed',
          summary: `已从 v${version.version_number} 创建恢复版本 v${restored.version_number}`,
        },
      ]);
      setMobilePanel('preview');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '恢复失败');
    } finally {
      setRestoringId(undefined);
    }
  };

  const publish = async () => {
    if (!project) return;
    setPublishing(true);
    setError('');
    try {
      const result = await api.publish(project.id);
      const url = new URL(window.location.href);
      url.search = '';
      url.searchParams.set('public', result.slug);
      setPublicUrl(url.toString());
      setProject(result.project);
      setProjects(current =>
        current.map(item =>
          item.id === result.project.id ? result.project : item,
        ),
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '发布失败');
    } finally {
      setPublishing(false);
    }
  };

  if (publicMode) {
    if (loading) {
      return (
        <div className="public-loading">
          <LoaderCircle className="spin" />
          正在打开应用…
        </div>
      );
    }
    if (error || !project || !spec) {
      return (
        <div className="public-error">
          <WifiOff size={32} />
          <h1>应用暂时无法访问</h1>
          <p>{error || '公开应用不存在'}</p>
        </div>
      );
    }
    return (
      <div className="public-page">
        <AppPreview
          initialRecords={publicRecords}
          projectId={project.id}
          publicMode
          spec={spec}
        />
      </div>
    );
  }

  return (
    <div className="workspace-app">
      <header className="system-bar">
        <div className="system-title">
          <span>PF</span>
          <strong>PromptForge</strong>
          <i>/</i>
          <em>{project?.name ?? '工作台'}</em>
        </div>
        <div className="system-statuses">
          <span>
            <Database size={13} />
            SQLite 本地模式
          </span>
          <span>
            <i className="status-pulse" />
            <Bot size={13} />
            本地 Agent
          </span>
          <span className="saved-status">
            <CheckCircle2 size={13} />
            自动保存
          </span>
        </div>
      </header>

      <nav className="mobile-tabs" aria-label="移动端面板切换">
        <button
          className={mobilePanel === 'projects' ? 'active' : ''}
          type="button"
          onClick={() => setMobilePanel('projects')}
        >
          <FolderKanban size={16} />
          项目
        </button>
        <button
          className={mobilePanel === 'studio' ? 'active' : ''}
          type="button"
          onClick={() => setMobilePanel('studio')}
        >
          <MessageSquareText size={16} />
          对话
        </button>
        <button
          className={mobilePanel === 'preview' ? 'active' : ''}
          type="button"
          onClick={() => setMobilePanel('preview')}
        >
          <Eye size={16} />
          预览
        </button>
      </nav>

      {error && (
        <div className="global-error">
          <WifiOff size={16} />
          <span>{error}</span>
          <button type="button" onClick={() => window.location.reload()}>
            <RefreshCw size={14} />
            重试
          </button>
          <button aria-label="关闭" type="button" onClick={() => setError('')}>
            ×
          </button>
        </div>
      )}

      <main className="workspace-grid">
        <div
          className={`mobile-panel projects-panel ${mobilePanel === 'projects' ? 'mobile-active' : ''}`}
        >
          <ProjectSidebar
            loading={loading}
            projects={projects}
            selectedId={project?.id}
            onCreate={createProject}
            onSelect={loadProject}
          />
        </div>

        <div
          className={`mobile-panel studio-column ${mobilePanel === 'studio' ? 'mobile-active' : ''}`}
        >
          {project ? (
            <StudioPanel
              generating={generating}
              messages={messages}
              project={project}
              restoringId={restoringId}
              steps={steps}
              versions={versions}
              onGenerate={generate}
              onRestore={restore}
            />
          ) : (
            <section className="studio-panel panel-surface empty-studio">
              <MessageSquareText size={28} />
              <h2>准备开始</h2>
              <p>请先从项目列表选择或创建一个项目。</p>
            </section>
          )}
        </div>

        <div
          className={`mobile-panel preview-column ${mobilePanel === 'preview' ? 'mobile-active' : ''}`}
        >
          {project && spec ? (
            <AppPreview
              key={`${project.id}-${versions[0]?.id ?? 'spec'}`}
              projectId={project.id}
              publicUrl={publicUrl}
              publishing={publishing}
              spec={spec}
              onPublish={publish}
            />
          ) : (
            <EmptyPreview noProject={!project} />
          )}
        </div>
      </main>
    </div>
  );
};

export default Page;

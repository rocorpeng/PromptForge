import { Box, ChevronRight, Database, Plus, Sparkles, X } from 'lucide-react';
import { useState } from 'react';
import type { Project } from '../types/promptforge';

interface ProjectSidebarProps {
  projects: Project[];
  selectedId?: Project['id'];
  loading: boolean;
  onSelect: (project: Project) => void;
  onCreate: (name: string, description: string) => Promise<void>;
}

export function ProjectSidebar({
  projects,
  selectedId,
  loading,
  onSelect,
  onCreate,
}: ProjectSidebarProps) {
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!name.trim()) return;
    setSubmitting(true);
    try {
      await onCreate(name.trim(), description.trim());
      setName('');
      setDescription('');
      setCreating(false);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <aside className="project-sidebar panel-surface">
      <div className="brand-lockup">
        <div className="brand-mark">
          <Sparkles size={19} strokeWidth={2.2} />
        </div>
        <div>
          <strong>PromptForge</strong>
          <span>LOCAL STUDIO</span>
        </div>
      </div>

      <button
        className="new-project-button"
        type="button"
        onClick={() => setCreating(true)}
      >
        <Plus size={17} />
        新建项目
      </button>

      <div className="sidebar-section-label">
        <span>项目空间</span>
        <span>{projects.length}</span>
      </div>
      <div className="project-list">
        {loading && <div className="sidebar-empty">正在读取本地项目…</div>}
        {!loading && projects.length === 0 && (
          <div className="sidebar-empty">
            <Box size={22} />
            <span>还没有项目</span>
            <small>创建一个空间开始生成</small>
          </div>
        )}
        {projects.map(project => (
          <button
            className={`project-item ${selectedId === project.id ? 'active' : ''}`}
            key={project.id}
            type="button"
            onClick={() => onSelect(project)}
          >
            <span className="project-icon">
              {project.name.slice(0, 1).toUpperCase()}
            </span>
            <span className="project-copy">
              <strong>{project.name}</strong>
              <small>
                v{project.latest_version_number ?? 0} ·{' '}
                {project.record_count ?? 0} 条数据
              </small>
            </span>
            <ChevronRight size={15} />
          </button>
        ))}
      </div>

      <div className="local-footnote">
        <Database size={14} />
        数据仅保存在本机
      </div>

      {creating && (
        <div className="modal-backdrop" role="presentation">
          <form className="create-dialog" onSubmit={submit}>
            <button
              aria-label="关闭"
              className="icon-button dialog-close"
              type="button"
              onClick={() => setCreating(false)}
            >
              <X size={18} />
            </button>
            <div className="dialog-orb">
              <Plus size={21} />
            </div>
            <h2>创建新项目</h2>
            <p>为你的下一款 AI 应用建立工作空间。</p>
            <label>
              项目名称
              <input
                maxLength={120}
                placeholder="例如：客户线索中心"
                value={name}
                onChange={event => setName(event.target.value)}
              />
            </label>
            <label>
              简短描述 <span>可选</span>
              <textarea
                placeholder="这个应用将解决什么问题？"
                rows={3}
                value={description}
                onChange={event => setDescription(event.target.value)}
              />
            </label>
            <button
              className="primary-button"
              disabled={submitting}
              type="submit"
            >
              {submitting ? '创建中…' : '创建项目'}
            </button>
          </form>
        </div>
      )}
    </aside>
  );
}

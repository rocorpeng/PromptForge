import {
  Bot,
  Check,
  ChevronDown,
  Clock3,
  CornerDownLeft,
  History,
  RotateCcw,
  Sparkles,
  UserRound,
} from 'lucide-react';
import { useState } from 'react';
import type {
  AgentStep,
  Message,
  Project,
  Version,
} from '../types/promptforge';

const EXAMPLES = [
  '创建一个客户线索管理器，支持搜索和状态筛选',
  '做一个团队任务看板，用卡片布局并标记优先级',
  '生成活动报名管理器，记录签到状态和参与人数',
  '创建用户反馈中心，支持评分、分类和处理状态',
];

interface StudioPanelProps {
  project: Project;
  messages: Message[];
  versions: Version[];
  steps: AgentStep[];
  generating: boolean;
  restoringId?: Version['id'];
  onGenerate: (prompt: string) => Promise<void>;
  onRestore: (version: Version) => Promise<void>;
}

const roleLabel = (role: string) => {
  if (role === 'user') return '你';
  if (role === 'team_lead') return '产品 Agent';
  return '构建 Agent';
};

export function StudioPanel({
  project,
  messages,
  versions,
  steps,
  generating,
  restoringId,
  onGenerate,
  onRestore,
}: StudioPanelProps) {
  const [prompt, setPrompt] = useState('');
  const [versionsOpen, setVersionsOpen] = useState(true);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const value = prompt.trim();
    if (!value || generating) return;
    setPrompt('');
    await onGenerate(value);
  };

  return (
    <section className="studio-panel panel-surface">
      <header className="studio-header">
        <div>
          <span className="eyebrow">AI BUILD SESSION</span>
          <h1>{project.name}</h1>
          <p>
            {project.description || '描述你的想法，Agent 会把它变成可用应用。'}
          </p>
        </div>
        <div className="agent-presence">
          <span /> 本地在线
        </div>
      </header>

      <div className="studio-scroll">
        {messages.length === 0 && !generating && (
          <div className="welcome-card">
            <div className="welcome-icon">
              <Sparkles size={23} />
            </div>
            <span>从一句话开始</span>
            <h2>你想构建什么？</h2>
            <p>描述业务对象、字段与操作。后续可以继续对话，逐步调整应用。</p>
          </div>
        )}

        <div className="message-stream">
          {messages.map(message => (
            <article
              className={`message ${message.role === 'user' ? 'user' : 'agent'}`}
              key={message.id}
            >
              <div className="message-avatar">
                {message.role === 'user' ? (
                  <UserRound size={15} />
                ) : (
                  <Bot size={15} />
                )}
              </div>
              <div>
                <span className="message-role">{roleLabel(message.role)}</span>
                <p>{message.content}</p>
              </div>
            </article>
          ))}
        </div>

        {(generating || steps.length > 0) && (
          <section
            className={`activity-card ${generating ? 'is-running' : ''}`}
          >
            <div className="activity-heading">
              <div>
                <Bot size={17} />
                <strong>Agent 活动</strong>
              </div>
              <span>{generating ? '构建中' : '已完成'}</span>
            </div>
            <div className="step-list">
              {steps.map((step, index) => (
                <div className="activity-step" key={`${step.agent}-${index}`}>
                  <span className={`step-dot ${step.status}`}>
                    {step.status === 'completed' ? (
                      <Check size={12} />
                    ) : (
                      index + 1
                    )}
                  </span>
                  <div>
                    <strong>
                      {step.agent === 'team_lead' ? '产品分析' : '应用构建'}
                    </strong>
                    <p>{step.summary}</p>
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        {versions.length > 0 && (
          <section className="versions-card">
            <button
              className="versions-heading"
              type="button"
              onClick={() => setVersionsOpen(!versionsOpen)}
            >
              <span>
                <History size={16} />
                版本记录
              </span>
              <ChevronDown
                className={versionsOpen ? 'rotated' : ''}
                size={16}
              />
            </button>
            {versionsOpen && (
              <div className="version-list">
                {versions.map((version, index) => (
                  <div className="version-item" key={version.id}>
                    <div className="version-node">
                      <span />
                    </div>
                    <div className="version-copy">
                      <div>
                        <strong>v{version.version_number}</strong>
                        {index === 0 && (
                          <span className="current-pill">当前</span>
                        )}
                      </div>
                      <p>{version.source_prompt || '应用版本'}</p>
                      <small>
                        <Clock3 size={12} />
                        {version.created_at
                          ? new Date(version.created_at).toLocaleString(
                              'zh-CN',
                              {
                                month: 'short',
                                day: 'numeric',
                                hour: '2-digit',
                                minute: '2-digit',
                              },
                            )
                          : '刚刚'}
                      </small>
                    </div>
                    {index !== 0 && (
                      <button
                        className="restore-button"
                        disabled={restoringId === version.id}
                        type="button"
                        onClick={() => onRestore(version)}
                      >
                        <RotateCcw size={13} />
                        {restoringId === version.id ? '恢复中' : '恢复'}
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </section>
        )}
      </div>

      <div className="prompt-dock">
        <div className="prompt-examples">
          {EXAMPLES.map((example, index) => (
            <button
              key={example}
              title={example}
              type="button"
              onClick={() => setPrompt(example)}
            >
              {index + 1}. {example}
            </button>
          ))}
        </div>
        <form className="prompt-box" onSubmit={submit}>
          <textarea
            aria-label="应用需求"
            placeholder="继续描述需求，例如“改成卡片布局并增加优先级筛选”…"
            rows={3}
            value={prompt}
            onChange={event => setPrompt(event.target.value)}
            onKeyDown={event => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
          />
          <div className="prompt-actions">
            <span>Enter 发送 · Shift + Enter 换行</span>
            <button
              aria-label="发送"
              disabled={!prompt.trim() || generating}
              type="submit"
            >
              {generating ? (
                <span className="button-spinner" />
              ) : (
                <CornerDownLeft size={17} />
              )}
            </button>
          </div>
        </form>
      </div>
    </section>
  );
}

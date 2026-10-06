import { AppWindow, ArrowLeft, Sparkles } from 'lucide-react';

interface EmptyPreviewProps {
  noProject?: boolean;
}

export function EmptyPreview({ noProject }: EmptyPreviewProps) {
  return (
    <div className="empty-preview">
      <div className="empty-preview-visual">
        <div className="preview-ghost-window">
          <div>
            <i />
            <i />
            <i />
          </div>
          <span>
            <AppWindow size={28} />
          </span>
        </div>
        <span className="float-spark one">
          <Sparkles size={14} />
        </span>
        <span className="float-spark two">
          <Sparkles size={11} />
        </span>
      </div>
      <h2>{noProject ? '选择或创建一个项目' : '预览即将在这里出现'}</h2>
      <p>
        {noProject
          ? '从左侧项目空间开始，你的创意会保存在本地。'
          : '向 Agent 描述你的应用，它会生成数据模型、界面与完整交互。'}
      </p>
      <span className="empty-hint">
        <ArrowLeft size={14} /> 在对话区输入 Prompt 开始
      </span>
    </div>
  );
}

/** 加载指示器:文字 + 脉冲点动画,用于 LLM 调用等待反馈。 */
export function LoadingDots({ text }: { text: string }) {
  return (
    <div className="loading-indicator">
      <span>{text}</span>
      <span className="dot" />
      <span className="dot" />
      <span className="dot" />
    </div>
  )
}
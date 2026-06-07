const STEPS = [
  { key: 'split', label: '书籍拆分' },
  { key: 'summary', label: '内容总结' },
  { key: 'recognition', label: '识别待处理' },
  { key: 'rewrite', label: 'AI 改写' },
  { key: 'merge', label: '合并输出' },
];

function dotState(done) {
  if (done === undefined) return 'todo';
  if (done === 'running') return 'active';
  if (done === 'done') return 'done';
  if (done === 'partial' || done === 'failed') return 'partial';
  return 'todo';
}

export function StepBar5({ splitDone, summaryDone, recognitionDone, rewriteDone, mergeDone }) {
  const states = {
    split: splitDone ? 'done' : 'todo',
    summary: summaryDone,
    recognition: recognitionDone,
    rewrite: rewriteDone,
    merge: mergeDone,
  };
  return (
    <ol className="enrichment-step-bar">
      {STEPS.map((s) => {
        const state = dotState(states[s.key]);
        return (
          <li key={s.key} className={`enrichment-step enrichment-step-${state}`}>
            <span className="enrichment-step-dot" />
            <span className="enrichment-step-label">{s.label}</span>
          </li>
        );
      })}
    </ol>
  );
}
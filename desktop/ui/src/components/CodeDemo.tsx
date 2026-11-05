/**
 * 演示窗口的「在线代码」面板:Linux 0.11 sched.c 片段
 * 逐行 typein 动画(每行延迟 0.14s),切回该 Tab 时重播
 */

type Seg = [text: string, cls?: string]

const LINES: Seg[][] = [
  [['/* sched.c — 调度核心 */', 'tk-com']],
  [['void', 'tk-key'], [' '], ['schedule', 'tk-fn'], ['('], ['void', 'tk-key'], [') {']],
  [['    '], ['int', 'tk-key'], [' c = '], ['-1', 'tk-num'], [', next = '], ['0', 'tk-num'], [';']],
  [['    '], ['struct', 'tk-key'], [' task_struct **p;']],
  [],
  [['    '], ['while', 'tk-key'], [' ('], ['1', 'tk-num'], [') {']],
  [['        '], ['for', 'tk-key'], [' (p = &LAST_TASK; p > &FIRST_TASK; --p)']],
  [['            '], ['if', 'tk-key'], [' ((*p) && (*p)->state == TASK_RUNNING)']],
  [['                '], ['if', 'tk-key'], [' ((*p)->counter > c)']],
  [['                    c = (*p)->counter, next = *p - task;']],
  [['        '], ['if', 'tk-key'], [' (c) '], ['break', 'tk-key'], [';']],
  [['        '], ['for', 'tk-key'], [' (p = &LAST_TASK; p > &FIRST_TASK; --p)']],
  [['            (*p)->counter = ((*p)->counter >> '], ['1', 'tk-num'], [') + (*p)->priority;']],
  [['    }']],
  [['    '], ['switch_to', 'tk-key'], ['(next);']],
  [['}']],
]

interface Props {
  /** 变化时重播逐行动画(切回代码 Tab) */
  replayKey?: number
}

export default function CodeDemo({ replayKey = 0 }: Props) {
  return (
    <pre>
      {LINES.map((segs, i) => (
        <span key={`${replayKey}-${i}`} className="line" style={{ animationDelay: `${i * 0.14}s` }}>
          <span className="ln">{i + 1}</span>
          <span className="src">
            {segs.map(([text, cls], j) =>
              cls ? (
                <span key={j} className={cls}>
                  {text}
                </span>
              ) : (
                <span key={j}>{text}</span>
              ),
            )}
          </span>
        </span>
      ))}
    </pre>
  )
}

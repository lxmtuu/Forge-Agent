import React from 'react'

/** Render unified diff — dòng + xanh, - đỏ, @@ cyan, header mờ. */
export function DiffView({ diff }: { diff: string }) {
  const lines = diff.split('\n')
  return (
    <pre className="diffview">
      {lines.map((ln, i) => {
        let cls = 'diff-ctx'
        if (ln.startsWith('+++') || ln.startsWith('---')) cls = 'diff-meta'
        else if (ln.startsWith('@@')) cls = 'diff-hunk'
        else if (ln.startsWith('+')) cls = 'diff-add'
        else if (ln.startsWith('-')) cls = 'diff-del'
        return <div key={i} className={`diff-line ${cls}`}>{ln || ' '}</div>
      })}
    </pre>
  )
}

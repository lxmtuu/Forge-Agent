import React from 'react'

/** Tiny safe markdown renderer: fenced code, inline code, bold, links, bullets. */

function renderInline(text: string, keyPrefix: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = []
  // split by inline code first, then bold, then links inside remaining text
  const re = /(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|(\[[^\]\n]+\]\([^)\s]+\))|(https?:\/\/[^\s<>()]+)/g
  let last = 0
  let m: RegExpExecArray | null
  let i = 0
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) nodes.push(text.slice(last, m.index))
    const tok = m[0]
    const k = `${keyPrefix}-i${i++}`
    if (tok.startsWith('`')) {
      nodes.push(<code key={k} className="md-code">{tok.slice(1, -1)}</code>)
    } else if (tok.startsWith('**')) {
      nodes.push(<strong key={k}>{tok.slice(2, -2)}</strong>)
    } else if (tok.startsWith('[')) {
      const mm = /\[([^\]\n]+)\]\(([^)\s]+)\)/.exec(tok)!
      nodes.push(<a key={k} href={mm[2]} target="_blank" rel="noreferrer">{mm[1]}</a>)
    } else {
      nodes.push(<a key={k} href={tok} target="_blank" rel="noreferrer">{tok}</a>)
    }
    last = m.index + tok.length
  }
  if (last < text.length) nodes.push(text.slice(last))
  return nodes
}

export function Markdown({ text }: { text: string }) {
  const blocks: React.ReactNode[] = []
  const lines = text.split('\n')
  let i = 0
  let bi = 0
  while (i < lines.length) {
    const line = lines[i]
    if (line.trimStart().startsWith('```')) {
      const lang = line.trim().slice(3).trim()
      const buf: string[] = []
      i++
      while (i < lines.length && !lines[i].trimStart().startsWith('```')) {
        buf.push(lines[i])
        i++
      }
      i++ // skip closing fence
      blocks.push(
        <pre key={`b${bi++}`} className="md-pre" data-lang={lang || undefined}>
          <code>{buf.join('\n')}</code>
        </pre>,
      )
      continue
    }
    if (/^\s*[-*]\s+/.test(line)) {
      const buf: string[] = []
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
        buf.push(lines[i].replace(/^\s*[-*]\s+/, ''))
        i++
      }
      blocks.push(
        <ul key={`b${bi++}`}>
          {buf.map((li, k) => <li key={k}>{renderInline(li, `b${bi}l${k}`)}</li>)}
        </ul>,
      )
      continue
    }
    if (/^\s*\d+[.)]\s+/.test(line)) {
      const buf: string[] = []
      while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) {
        buf.push(lines[i].replace(/^\s*\d+[.)]\s+/, ''))
        i++
      }
      blocks.push(
        <ol key={`b${bi++}`}>
          {buf.map((li, k) => <li key={k}>{renderInline(li, `b${bi}l${k}`)}</li>)}
        </ol>,
      )
      continue
    }
    if (line.trim() === '') {
      i++
      continue
    }
    // paragraph: join until blank line
    const buf: string[] = []
    while (i < lines.length && lines[i].trim() !== '' &&
           !lines[i].trimStart().startsWith('```') &&
           !/^\s*([-*]|\d+[.)])\s+/.test(lines[i])) {
      buf.push(lines[i])
      i++
    }
    blocks.push(<p key={`b${bi++}`}>{renderInline(buf.join('\n'), `b${bi}`)}</p>)
  }
  return <div className="md">{blocks}</div>
}

import React, { useState } from 'react'

/** Safe markdown renderer: fenced code (with copy button), headings, quote, hr, bold, inline code, links, lists. */

function renderInline(text: string, keyPrefix: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = []
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

function CodeBlock({ code, lang }: { code: string; lang: string }) {
  const [copied, setCopied] = useState(false)
  async function copy() {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
      setTimeout(() => setCopied(false), 1600)
    } catch { /* clipboard blocked */ }
  }
  return (
    <div className="md-codeblock">
      <div className="md-codebar">
        <span className="md-codelang">{lang || 'code'}</span>
        <button className="md-codecopy" onClick={copy}>{copied ? '✓ đã copy' : '⧉ copy'}</button>
      </div>
      <pre className="md-pre"><code>{code}</code></pre>
    </div>
  )
}

export function Markdown({ text }: { text: string }) {
  const blocks: React.ReactNode[] = []
  const lines = text.split('\n')
  let i = 0
  let bi = 0
  while (i < lines.length) {
    const line = lines[i]

    // fenced code
    if (line.trimStart().startsWith('```')) {
      const lang = line.trim().slice(3).trim()
      const buf: string[] = []
      i++
      while (i < lines.length && !lines[i].trimStart().startsWith('```')) {
        buf.push(lines[i])
        i++
      }
      i++
      blocks.push(<CodeBlock key={`b${bi++}`} code={buf.join('\n')} lang={lang} />)
      continue
    }

    // headings
    const hm = /^(#{1,3})\s+(.*)$/.exec(line)
    if (hm && !hm[2].startsWith('#')) {
      const level = hm[1].length
      const content = renderInline(hm[2], `h${bi}`)
      blocks.push(
        level === 1
          ? <h1 key={`b${bi++}`} className="md-h md-h1">{content}</h1>
          : level === 2
            ? <h2 key={`b${bi++}`} className="md-h md-h2">{content}</h2>
            : <h3 key={`b${bi++}`} className="md-h md-h3">{content}</h3>,
      )
      i++
      continue
    }

    // horizontal rule
    if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
      blocks.push(<hr key={`b${bi++}`} className="md-hr" />)
      i++
      continue
    }

    // blockquote
    if (line.trimStart().startsWith('>')) {
      const buf: string[] = []
      while (i < lines.length && lines[i].trimStart().startsWith('>')) {
        buf.push(lines[i].replace(/^\s*>\s?/, ''))
        i++
      }
      blocks.push(
        <blockquote key={`b${bi++}`} className="md-quote">
          {renderInline(buf.join('\n'), `q${bi}`)}
        </blockquote>,
      )
      continue
    }

    // unordered list
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

    // ordered list
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

    // paragraph
    const buf: string[] = []
    while (i < lines.length && lines[i].trim() !== '' &&
           !lines[i].trimStart().startsWith('```') &&
           !lines[i].trimStart().startsWith('>') &&
           !/^(#{1,3})\s+/.test(lines[i]) &&
           !/^\s*([-*]|\d+[.)])\s+/.test(lines[i]) &&
           !/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(lines[i])) {
      buf.push(lines[i])
      i++
    }
    blocks.push(<p key={`b${bi++}`}>{renderInline(buf.join('\n'), `b${bi}`)}</p>)
  }
  return <div className="md">{blocks}</div>
}

import React, { useState } from 'react'
import type { Item } from '../types'
import { useI18n } from '../i18n'

type Schema = NonNullable<Extract<Item, { kind: 'elicitation' }>['schema']>

/** Form trả lời elicitation MCP (spec 2026-07-28): accept/decline/cancel. */
export function ElicitationCard(props: {
  item: Extract<Item, { kind: 'elicitation' }>
  onResolve: (eid: string, action: string, content?: Record<string, unknown>) => void
}) {
  const { t } = useI18n()
  const { item } = props
  const propsSchema: Schema['properties'] = item.schema?.properties ?? {}
  const required: string[] = item.schema?.required ?? []
  const [values, setValues] = useState<Record<string, string | boolean>>({})
  const [missing, setMissing] = useState<string[]>([])
  const answered = item.action !== null

  function submit() {
    const miss = required.filter((k) => {
      const v = values[k]
      return v === undefined || v === '' || v === false && propsSchema[k]?.type !== 'boolean'
    })
    if (miss.length) { setMissing(miss); return }
    const content: Record<string, unknown> = {}
    for (const [k, def] of Object.entries(propsSchema)) {
      const v = values[k]
      if (v === undefined) continue
      if (def?.type === 'number') { const n = parseFloat(String(v)); if (Number.isFinite(n)) content[k] = n }
      else if (def?.type === 'boolean') content[k] = Boolean(v)
      else if (def?.type === 'string[]') content[k] = String(v).split(',').map((s) => s.trim()).filter(Boolean)
      else content[k] = String(v)
    }
    props.onResolve(item.eid, 'accept', content)
  }

  return (
    <div className="msg">
      <div className="elic-card">
        <div className="elic-head">🔔 <b>{item.server}</b> {t('cần bạn cung cấp thông tin (MCP elicitation)', 'needs additional information (MCP elicitation)')}</div>
        <div className="elic-msg">{item.message || '—'}</div>

        {item.url && (
          <div className="elic-url">
            {t('Mở URL này nếu bạn muốn tiếp tục (Forge', 'Open this URL if you want to continue (Forge')} <b>{t('không tự mở', 'does not open it automatically')}</b>):<br />
            <code>{item.url}</code>
          </div>
        )}

        {!item.url && Object.keys(propsSchema).length > 0 && !answered && (
          <div className="elic-form">
            {Object.entries(propsSchema).map(([k, def]) => (
              <label key={k} className="elic-field">
                <span>
                  {def?.description || k}
                  {required.includes(k) && <em className="elic-req"> *</em>}
                  <small className="elic-type">{k} · {def?.type}</small>
                </span>
                {def?.type === 'boolean' ? (
                  <input type="checkbox" checked={Boolean(values[k])}
                    onChange={(e) => setValues((v) => ({ ...v, [k]: e.target.checked }))} />
                ) : (
                  <input
                    type={def?.type === 'number' ? 'number' : 'text'}
                    value={String(values[k] ?? '')}
                    placeholder={def?.type === 'string[]' ? t('giá-trị-1, giá-trị-2', 'value-1, value-2') : ''}
                    onChange={(e) => setValues((v) => ({ ...v, [k]: e.target.value }))}
                  />
                )}
              </label>
            ))}
            {missing.length > 0 && (
              <div className="elic-missing">{t('Thiếu trường bắt buộc:', 'Missing required fields:')} {missing.join(', ')}</div>
            )}
          </div>
        )}

        {answered ? (
          <div className="elic-done">{t('→ Đã trả lời:', '→ Response:')} <b>{item.action}</b></div>
        ) : (
          <div className="elic-actions">
            {!item.url && Object.keys(propsSchema).length > 0 && (
              <button className="elic-btn ok" onClick={submit}>{t('✓ Gửi', '✓ Submit')}</button>
            )}
            {!item.url && Object.keys(propsSchema).length === 0 && (
              <button className="elic-btn ok" onClick={() => props.onResolve(item.eid, 'accept')}>{t('✓ Xác nhận', '✓ Confirm')}</button>
            )}
            <button className="elic-btn bad" onClick={() => props.onResolve(item.eid, 'decline')}>{t('✕ Từ chối', '✕ Decline')}</button>
            <button className="elic-btn dim" onClick={() => props.onResolve(item.eid, 'cancel')}>{t('Đóng', 'Close')}</button>
          </div>
        )}
      </div>
    </div>
  )
}

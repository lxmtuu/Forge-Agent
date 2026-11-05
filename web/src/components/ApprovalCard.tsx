import React, { useState } from 'react'
import { api } from '../api'
import type { Item } from '../types'
import { useI18n } from '../i18n'

export function ApprovalCard({
  item,
  onResolved,
}: {
  item: Extract<Item, { kind: 'approval' }>
  onResolved: (approvalId: string, decision: string) => void
}) {
  const { t } = useI18n()
  const [busy, setBusy] = useState(false)
  const decided = item.decision !== null

  async function decide(decision: 'approve' | 'approve_always' | 'deny') {
    if (decided || busy) return
    setBusy(true)
    try {
      await api.resolveApproval(item.approvalId, decision)
      onResolved(item.approvalId, decision)
    } catch { /* request may already be resolved by timeout */ onResolved(item.approvalId, 'deny') }
    finally { setBusy(false) }
  }

  return (
    <div className={`approval-card ${decided ? 'resolved' : 'pending'}`}>
      <div className="approval-head">
        <span className="approval-icon">{decided ? '🔒' : '🔔'}</span>
        <b>{t('Phê duyệt lệnh shell', 'Shell command approval')}</b>
        <span className={`st ${item.level === 'danger' ? 'st-bad' : 'st-warn'}`}>{item.level}</span>
        {item.decision && (
          <span className={`st ${item.decision === 'deny' ? 'st-bad' : 'st-ok'}`}>
            {item.decision === 'approve' ? t('đã chấp nhận', 'approved') : item.decision === 'approve_always' ? t('luôn cho phép', 'always allowed') : t('đã từ chối', 'denied')}
          </span>
        )}
      </div>
      <pre className="approval-cmd">{item.command}</pre>
      {item.reasons.length > 0 && (
        <div className="approval-reasons">
          {item.reasons.map((r) => <span key={r} className="reason-chip">{r}</span>)}
        </div>
      )}
      {!decided && (
        <div className="approval-actions">
          <button className="btn-ok" disabled={busy} onClick={() => decide('approve')}>{t('✓ Chấp nhận', '✓ Approve')}</button>
          <button className="btn-ok-outline" disabled={busy} onClick={() => decide('approve_always')}>{t('✓✓ Luôn cho phép lệnh này', '✓✓ Always allow this command')}</button>
          <button className="btn-no" disabled={busy} onClick={() => decide('deny')}>{t('✕ Từ chối', '✕ Deny')}</button>
        </div>
      )}
    </div>
  )
}

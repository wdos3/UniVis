import { BadgeCheck, CircleAlert, CircleHelp, Image } from 'lucide-react'
import type { GroundedItem } from '../types'

const stateLabels = {
  verified: { label: 'Verified from notice', Icon: BadgeCheck },
  needs_review: { label: 'Needs review', Icon: CircleAlert },
  not_stated: { label: 'Not stated', Icon: CircleHelp },
} as const

export function Evidence({ item, visible, onViewImage }: { item: GroundedItem; visible: boolean; onViewImage?: (item: GroundedItem) => void }) {
  if (!visible) return null
  const state = stateLabels[item.state]
  return (
    <aside className={`evidence evidence--${item.state}`} aria-label="Source evidence">
      <span className="evidence__state"><state.Icon size={14} aria-hidden="true" /> {state.label}</span>
      {item.source_evidence && <><span className="evidence__source" lang="ko">{item.source_evidence}</span><span className="fact-ids">{item.source_fact_ids.join(', ')}</span></>}
      {item.source_page && onViewImage && <button className="evidence__image" onClick={() => onViewImage(item)}><Image size={13} />View on page {item.source_page}</button>}
    </aside>
  )
}

import { useState } from 'react'
import type { Item } from '../lib/api'
import { useAssistant } from '../lib/assistant'
import { FOLLOW_UP_WORKING_DAYS, useItemAction } from '../lib/items'
import { UpdateDialog } from './UpdateDialog'

type Dialog = { item: Item; purpose: 'update' | 'assign' | 'dismiss'; note?: string }

/**
 * Starting the work on an item. A message opens as a draft in the side pane, a
 * bill with no job gets a suggested job there, and the rest are a choice in a
 * dialog or a single change. Nothing here contacts anyone on its own.
 */
export function useItemWork() {
  const { show } = useAssistant()
  const act = useItemAction()
  const [dialog, setDialog] = useState<Dialog | null>(null)

  function start(item: Item, suggestion: Item['suggestion'] = item.suggestion) {
    const { key } = suggestion.action
    if (key === 'message_customer' || key === 'message_colleague') show({ kind: 'draft', item })
    else if (key === 'code_bill') show({ kind: 'coding', item })
    else if (key === 'assign_ops_manager') setDialog({ item, purpose: 'assign' })
    else if (key === 'dismiss') setDialog({ item, purpose: 'dismiss', note: suggestion.reason ?? '' })
    else {
      // Wait: set the date to come back, and say why in the history.
      act.mutate({
        item,
        action: 'update',
        note: suggestion.reason ? `Waiting. ${suggestion.reason}` : undefined,
        ...(suggestion.follow_up_on
          ? { follow_up_on: suggestion.follow_up_on }
          : { follow_up_in_working_days: FOLLOW_UP_WORKING_DAYS }),
      })
    }
  }

  return {
    start,
    update: (item: Item) => setDialog({ item, purpose: 'update' }),
    dismiss: (item: Item) => setDialog({ item, purpose: 'dismiss' }),
    reopen: (item: Item) => act.mutate({ item, action: 'reopen' }),
    busy: act.isPending,
    dialogs: dialog && <UpdateDialog key={dialog.item.key} {...dialog} onClose={() => setDialog(null)} />,
  }
}

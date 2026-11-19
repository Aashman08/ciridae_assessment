/** Joins class names, skipping anything falsy. */
export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(' ')
}

/** The look of a button, shared with the few links that should read as one. */
export function buttonClass(variant: 'quiet' | 'primary' = 'quiet', className?: string): string {
  return cx(
    'inline-flex h-8 items-center justify-center gap-2 rounded-lg px-3 text-[13px] whitespace-nowrap',
    'transition-[background-color,transform,opacity] duration-150 ease-out active:scale-[0.98] disabled:opacity-50 disabled:active:scale-100',
    variant === 'primary' ? 'bg-btn text-btn-ink' : 'border border-hair bg-raised hover:bg-card',
    className,
  )
}

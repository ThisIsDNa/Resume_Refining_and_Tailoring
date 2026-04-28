type GenerateButtonProps = {
  loading?: boolean
  disabled?: boolean
  onClick?: () => void
  type?: 'button' | 'submit'
}

export function GenerateButton({ loading, disabled, onClick, type = 'submit' }: GenerateButtonProps) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled || loading}
      className="inline-flex items-center justify-center rounded-md bg-violet-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-violet-500 disabled:cursor-not-allowed disabled:opacity-60"
    >
      {loading ? 'Tailoring…' : 'Tailor'}
    </button>
  )
}

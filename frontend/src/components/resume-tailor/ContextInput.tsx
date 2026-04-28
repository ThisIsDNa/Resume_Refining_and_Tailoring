type ContextInputProps = {
  value: string
  onChange: (value: string) => void
  disabled?: boolean
}

export function ContextInput({ value, onChange, disabled }: ContextInputProps) {
  return (
    <div className="flex flex-col gap-2">
      <label htmlFor="context" className="text-sm font-medium text-zinc-800 dark:text-zinc-200">
        Optional context
      </label>
      <textarea
        id="context"
        name="context"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        rows={4}
        placeholder="Company focus, role nuances, or constraints (optional)."
        className="w-full resize-y rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 placeholder:text-zinc-400 focus:border-violet-500 focus:outline-none focus:ring-1 focus:ring-violet-500 dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-100 dark:placeholder:text-zinc-500"
      />
    </div>
  )
}

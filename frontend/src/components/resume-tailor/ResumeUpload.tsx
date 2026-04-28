type ResumeUploadProps = {
  id?: string
  fileName: string | null
  onFileChange: (file: File | null) => void
  disabled?: boolean
}

export function ResumeUpload({ id = 'resume-file', fileName, onFileChange, disabled }: ResumeUploadProps) {
  return (
    <div className="flex flex-col gap-2">
      <label htmlFor={id} className="text-sm font-medium text-zinc-800 dark:text-zinc-200">
        Resume (.docx)
      </label>
      <input
        id={id}
        name="resume_file"
        type="file"
        accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        disabled={disabled}
        className="block w-full cursor-pointer rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 file:mr-3 file:rounded file:border-0 file:bg-zinc-100 file:px-3 file:py-1 file:text-sm dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-100 dark:file:bg-zinc-800"
        onChange={(e) => {
          const f = e.target.files?.[0] ?? null
          onFileChange(f)
        }}
      />
      {fileName ? (
        <p className="text-xs text-zinc-500 dark:text-zinc-400">Selected: {fileName}</p>
      ) : (
        <p className="text-xs text-zinc-500 dark:text-zinc-400">Upload your resume as a Word document.</p>
      )}
    </div>
  )
}

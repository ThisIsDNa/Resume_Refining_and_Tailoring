/** Thrown when POST /refinery/export returns 422 with structured validation checks. */
export class RefineryExportValidationError extends Error {
  readonly checks: string[]

  constructor(message: string, checks: string[]) {
    super(message)
    this.name = 'RefineryExportValidationError'
    this.checks = checks
  }
}

const REFINERY_EXPORT_URL = 'http://localhost:8000/refinery/export'

function parseContentDispositionFilename(header: string | null): string | null {
  if (!header) return null
  const quoted = /filename="([^"]+)"/i.exec(header)
  if (quoted) return quoted[1]
  const star = /filename\*=UTF-8''([^;\s]+)/i.exec(header)
  if (star) return decodeURIComponent(star[1])
  const plain = /filename=([^;\s]+)/i.exec(header)
  if (plain) return plain[1].replace(/^["']|["']$/g, '')
  return null
}

function formatErrorDetail(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((d) => (typeof d === 'object' && d && 'msg' in d ? String((d as { msg: string }).msg) : String(d)))
      .join('; ')
  }
  if (detail && typeof detail === 'object' && 'detail' in detail) {
    return formatErrorDetail((detail as { detail: unknown }).detail)
  }
  return 'Request failed'
}

export type RefineryExportOptions = {
  /** Ids the user chose in ChangeReviewPanel; backend may ignore until selective apply is implemented. */
  selectedChangeIds?: string[]
}

/**
 * POST multipart form to /refinery/export; triggers a .docx download on success.
 */
export async function postRefineryExportDocx(formData: FormData, options?: RefineryExportOptions): Promise<void> {
  // TODO: Refinery export should apply only selected improvements when the backend honors `selected_change_ids`.
  if (options?.selectedChangeIds !== undefined) {
    formData.append('selected_change_ids', JSON.stringify(options.selectedChangeIds))
  }

  const res = await fetch(REFINERY_EXPORT_URL, {
    method: 'POST',
    body: formData,
  })

  if (res.ok) {
    const filename =
      parseContentDispositionFilename(res.headers.get('Content-Disposition')) ?? 'refinery_resume.docx'
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.rel = 'noopener'
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
    return
  }

  if (res.status === 422) {
    const body = (await res.json().catch(() => null)) as unknown
    const detail =
      body && typeof body === 'object' && body !== null && 'detail' in body
        ? (body as { detail: unknown }).detail
        : null
    if (detail && typeof detail === 'object' && detail !== null) {
      const d = detail as { status?: unknown; checks?: unknown }
      const checks = Array.isArray(d.checks) ? d.checks.map((x) => String(x)) : []
      const status = typeof d.status === 'string' ? d.status : 'DOCX EXPORT FAILED'
      throw new RefineryExportValidationError(status, checks)
    }
    throw new RefineryExportValidationError('DOCX EXPORT FAILED', [])
  }

  const text = await res.text().catch(() => '')
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch {
    parsed = null
  }
  if (parsed && typeof parsed === 'object' && parsed !== null && 'detail' in parsed) {
    throw new Error(formatErrorDetail((parsed as { detail: unknown }).detail))
  }
  throw new Error(text.trim() || `Export failed (${res.status})`)
}

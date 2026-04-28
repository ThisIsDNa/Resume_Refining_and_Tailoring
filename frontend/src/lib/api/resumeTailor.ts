import type { GenerateResponse } from '@/types/resumeTailor'

const GENERATE_URL = 'http://localhost:8000/generate'
export const EXPORT_DOCX_URL = 'http://localhost:8000/export/docx'

/** Thrown when POST /export/docx returns 422 with structured validation checks. */
export class ExportDocxValidationError extends Error {
  readonly checks: string[]

  constructor(message: string, checks: string[]) {
    super(message)
    this.name = 'ExportDocxValidationError'
    this.checks = checks
  }
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

export async function generateTailoredResume(formData: FormData): Promise<GenerateResponse> {
  const res = await fetch(GENERATE_URL, {
    method: 'POST',
    body: formData,
  })

  if (!res.ok) {
    const body = await res.json().catch(() => null)
    const detail = body && typeof body === 'object' && 'detail' in body ? (body as { detail: unknown }).detail : res.statusText
    throw new Error(formatErrorDetail(detail))
  }

  return res.json() as Promise<GenerateResponse>
}

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

export type TailorExportDocxOptions = {
  /** Ids from ChangeReviewPanel; backend may ignore until selective apply is implemented. */
  selectedChangeIds?: string[]
}

/**
 * POST multipart form to /export/docx (no Content-Type header — browser sets boundary for FormData).
 * On 200: triggers a file download of the returned .docx.
 */
export async function exportDocxResume(formData: FormData, options?: TailorExportDocxOptions): Promise<void> {
  // TODO: Tailor export should apply only selected tailoring changes when the backend honors `selected_change_ids`.
  if (options?.selectedChangeIds !== undefined) {
    formData.append('selected_change_ids', JSON.stringify(options.selectedChangeIds))
  }

  const res = await fetch(EXPORT_DOCX_URL, {
    method: 'POST',
    body: formData,
  })

  if (res.ok) {
    const filename =
      parseContentDispositionFilename(res.headers.get('Content-Disposition')) ?? 'Dustin_Na_Resume_Tailored.docx'
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
      throw new ExportDocxValidationError(status, checks)
    }
    throw new ExportDocxValidationError('DOCX EXPORT FAILED', [])
  }

  const text = await res.text().catch(() => '')
  throw new Error(text.trim() || `Export failed (${res.status})`)
}

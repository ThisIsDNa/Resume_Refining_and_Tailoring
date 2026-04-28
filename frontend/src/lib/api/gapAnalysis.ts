import type { GapAnalysisResponse } from '@/types/gapAnalysis'

const GAP_ANALYSIS_URL = 'http://localhost:8000/gap-analysis'

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

export async function postGapAnalysis(formData: FormData): Promise<GapAnalysisResponse> {
  const res = await fetch(GAP_ANALYSIS_URL, {
    method: 'POST',
    body: formData,
  })

  if (!res.ok) {
    const body = await res.json().catch(() => null)
    const detail =
      body && typeof body === 'object' && 'detail' in body ? (body as { detail: unknown }).detail : res.statusText
    throw new Error(formatErrorDetail(detail))
  }

  return res.json() as Promise<GapAnalysisResponse>
}

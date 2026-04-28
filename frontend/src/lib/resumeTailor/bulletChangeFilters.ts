import type { PrioritizedBulletChange } from '@/types/resumeTailor'

const EMAIL_LIKE = /@\S+\.\S+/
const PHONE_LIKE = /\b(?:\+?\d{1,2}[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?){2}\d{4}\b/
/** Strip common URL / profile patterns for junk detection (global). */
function stripUrlsAndProfiles(t: string): string {
  return t
    .replace(/https?:\/\/[^\s]+/gi, '')
    .replace(/\bwww\.[^\s]+/gi, '')
    .replace(/linkedin\.com\/[^\s]*/gi, '')
    .replace(/github\.com\/[^\s]*/gi, '')
    .replace(/mailto:\S+/gi, '')
    .replace(/tel:\S+/gi, '')
}

const PROFILE_OR_CONTACT_HINT = /\b(mailto:|tel:|linkedin\.com|github\.com)\b/i

function norm(s: string | undefined) {
  return (s ?? '').replace(/\s+/g, ' ').trim().toLowerCase()
}

/** Higher = worse candidate for “top” placement. */
function lowValueScore(b: PrioritizedBulletChange): number {
  const before = b.before ?? ''
  const after = b.after ?? ''
  const t = `${before} ${after}`
  let score = 0

  if (t.length < 22) score += 5
  else if (t.length < 42) score += 2

  const stripped = stripUrlsAndProfiles(t)
  const strippedRatio = stripped.length / Math.max(t.length, 1)
  if (strippedRatio < 0.5) score += 6
  else if (strippedRatio < 0.72) score += 3

  if (PROFILE_OR_CONTACT_HINT.test(t)) score += 4
  if (EMAIL_LIKE.test(t) && t.length < 120) score += 5
  if (PHONE_LIKE.test(t) && t.length < 130) score += 4

  const nb = norm(before)
  const na = norm(after)
  if (nb && na) {
    if (nb === na) score += 4
    else if (Math.abs(nb.length - na.length) < 6 && (nb.startsWith(na) || na.startsWith(nb))) score += 3
  }

  return score
}

/** Drop only rows that are clearly non-content (noise / contact-only). */
function shouldOmitEntirely(b: PrioritizedBulletChange): boolean {
  const t = `${b.before ?? ''} ${b.after ?? ''}`.trim()
  if (t.length < 10) return true
  const score = lowValueScore(b)
  if (score >= 11) return true
  if (t.length < 20 && score >= 7) return true
  const stripped = stripUrlsAndProfiles(t).replace(/\s+/g, '').length
  if (stripped < 14 && t.length < 100) return true
  if (EMAIL_LIKE.test(t) && t.length < 90) return true
  return false
}

/**
 * Deprioritize weak rows and omit obvious junk. Preserves a stable order for ties.
 * Does not change backend data — display-only.
 */
export function prioritizeBulletChangesForDisplay(
  bullets: PrioritizedBulletChange[],
): PrioritizedBulletChange[] {
  const list = bullets ?? []
  const kept = list.filter((b) => !shouldOmitEntirely(b))
  return kept
    .map((b, originalIndex) => ({ b, originalIndex, w: lowValueScore(b) }))
    .sort((a, b) => {
      if (a.w !== b.w) return a.w - b.w
      return a.originalIndex - b.originalIndex
    })
    .map(({ b }) => b)
}

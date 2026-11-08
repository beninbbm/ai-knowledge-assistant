// Turn "[1]" citation markers in an answer into Markdown links "[1](#cite-1)", so the
// Markdown renderer hands them to our CitationChip component instead of printing text.

const CITATION = /\[(\d+)\](?!\()/g

export function linkCitations(answer: string): string {
  return answer.replace(CITATION, (_, n: string) => `[${n}](#cite-${n})`)
}

export function citationNumber(href: string | undefined): number | null {
  const match = href?.match(/^#cite-(\d+)$/)
  return match ? Number(match[1]) : null
}

/** "Leave Policy › Parental Leave · p. 3" — where a passage sits in its document. */
export function describeLocation(
  headingPath: string[],
  pageStart: number | null,
  pageEnd: number | null,
): string {
  // The first heading is usually the document's own title, already shown separately.
  const path = headingPath.slice(headingPath.length > 1 ? 1 : 0).join(' › ')
  let pages = ''
  if (pageStart) pages = pageStart === pageEnd || !pageEnd ? `p. ${pageStart}` : `pp. ${pageStart}–${pageEnd}`
  return [path, pages].filter(Boolean).join(' · ')
}

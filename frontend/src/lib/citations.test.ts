import { describe, expect, it } from 'vitest'
import { citationNumber, describeLocation, linkCitations } from './citations'

describe('linkCitations', () => {
  it('turns [n] into citation links', () => {
    expect(linkCitations('16 weeks [1][3].')).toBe('16 weeks [1](#cite-1)[3](#cite-3).')
  })
  it('leaves existing Markdown links alone', () => {
    expect(linkCitations('see [2](http://x)')).toBe('see [2](http://x)')
  })
})

describe('citationNumber', () => {
  it('reads the number back from the link', () => {
    expect(citationNumber('#cite-12')).toBe(12)
    expect(citationNumber('https://example.com')).toBeNull()
  })
})

describe('describeLocation', () => {
  it('drops the document title and adds pages', () => {
    expect(describeLocation(['Policy', 'Hotels'], 1, 1)).toBe('Hotels · p. 1')
    expect(describeLocation(['Policy', 'A', 'B'], 2, 4)).toBe('A › B · pp. 2–4')
    expect(describeLocation(['Only title'], null, null)).toBe('Only title')
  })
})

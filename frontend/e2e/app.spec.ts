import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import path from 'node:path'

const SAMPLES = path.resolve(import.meta.dirname, '../../samples')
const SHOTS = path.resolve(import.meta.dirname, 'screenshots')
const PASSWORD = 'e2e-password-123'
const stamp = Date.now()

async function register(page: Page, email: string) {
  await page.goto('/')
  await page.getByRole('tab', { name: 'Create account' }).click()
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(PASSWORD)
  await page.getByRole('button', { name: 'Create account' }).click()
  await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible()
}

test('upload, ask, check citations, follow up, and stay private', async ({ page, browser }) => {
  const alice = `e2e-alice-${stamp}@example.com`
  await register(page, alice)

  // --- Upload the three sample documents and wait until they're processed.
  await page.getByRole('link', { name: 'Documents' }).click()
  await page.locator('input[type=file]').setInputFiles([
    path.join(SAMPLES, 'employee-handbook.md'),
    path.join(SAMPLES, 'it-security-policy.docx'),
    path.join(SAMPLES, 'travel-expense-policy.pdf'),
  ])
  await expect(page.locator('.doc-row')).toHaveCount(3)
  await page.screenshot({ path: `${SHOTS}/1-library-processing.png` })
  await expect(page.locator('.badge-ready')).toHaveCount(3)
  await page.screenshot({ path: `${SHOTS}/2-library-ready.png` })

  // --- Inspect how a document was chunked.
  await page.locator('.doc-row', { hasText: 'travel-expense-policy' }).getByRole('button', { name: 'View chunks' }).click()
  await expect(page.getByRole('dialog')).toContainText('Hotels and Daily Allowances')
  await page.screenshot({ path: `${SHOTS}/3-chunks.png` })
  await page.getByRole('button', { name: 'Close' }).click()

  // --- Ask a question and get a cited answer.
  await page.getByRole('link', { name: 'Chat' }).click()
  await expect(page.getByText(/Answers come only from the 3 documents/)).toBeVisible()
  await page.getByLabel('Your question').fill('How much parental leave do primary caregivers get?')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.getByRole('status')).toBeVisible() // "Searching…" / "Reading…"
  await page.screenshot({ path: `${SHOTS}/4-thinking.png` })
  const firstAnswer = page.locator('.assistant-message').first()
  await expect(firstAnswer.locator('.sources')).toBeVisible()
  await expect(firstAnswer).toContainText('16 weeks')

  // --- Click the citation chip: the source panel shows the passage.
  await firstAnswer.locator('.answer-text button.cite-chip').first().click()
  const panel = page.getByRole('complementary', { name: 'Source passage' })
  await expect(panel).toContainText('Parental Leave')
  await expect(panel.locator('.passage-cited')).toContainText('16 weeks')
  await page.screenshot({ path: `${SHOTS}/5-answer-with-source.png` })
  await panel.getByRole('button', { name: 'Close source' }).click()

  // --- Follow-up question: rewritten for search, answered in context.
  await page.getByLabel('Your question').fill('what about contractors?')
  await page.keyboard.press('Enter')
  await expect(page.getByText(/Searched for: .*contractor/i)).toBeVisible()
  const secondAnswer = page.locator('.assistant-message').nth(1)
  await expect(secondAnswer.locator('.sources')).toBeVisible()
  await expect(secondAnswer).toContainText(/not eligible|unpaid/i)
  await page.screenshot({ path: `${SHOTS}/6-follow-up.png` })

  // --- The conversation is saved and listed in the sidebar.
  await expect(page.locator('.conversation-link')).toHaveCount(1)
  await page.reload()
  await expect(page.locator('.assistant-message')).toHaveCount(2)

  // --- A second user sees none of Alice's documents.
  const bobContext = await browser.newContext()
  const bob = await bobContext.newPage()
  await register(bob, `e2e-bob-${stamp}@example.com`)
  await expect(bob.getByText(/don't have any searchable documents/)).toBeVisible()
  await bob.getByRole('link', { name: 'Documents' }).click()
  await expect(bob.getByText("Nobody has shared a document with you yet.")).toBeVisible()
  await bob.getByRole('link', { name: 'Chat' }).click()
  await bob.getByLabel('Your question').fill('How much parental leave do primary caregivers get?')
  await bob.getByRole('button', { name: 'Send' }).click()
  await expect(bob.locator('.assistant-message')).toContainText("couldn't find anything")
  await bob.screenshot({ path: `${SHOTS}/7-other-user-isolated.png` })
  await bobContext.close()
})

import { afterEach, describe, expect, it, vi } from 'vitest'
import { makeSourceUnit, pendingLedger } from './sourceLedger'
import { planRecoveryCrops, recoveryCrops } from './crops'

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

describe('bounded image-region recovery', () => {
  it('prioritizes conflicting contact digits ahead of small decorative seal text', () => {
    const seal = Array.from({ length: 5 }, (_, order) => ({ ...makeSourceUnit({ page: 1, text: '인', order, id: `seal-${order}`,
      box: { x: .1, y: .1 + order * .02, width: .03, height: .01 }, confidence: .4 }), translation_status: 'source_crop' as const }))
    const contact = { ...makeSourceUnit({ page: 1, text: '문의 02.710.25n0', order: 10, id: 'contact', box: { x: .1, y: .9, width: .4, height: .02 }, confidence: .99 }),
      translation_status: 'translated' as const, alternatives: [{ text: '문의 02.710.25n0', pass_name: 'initial' }, { text: '문의 02.710.2500', pass_name: 'detail' }] }
    const plans = planRecoveryCrops(pendingLedger([...seal, contact]))
    expect(plans[0].unit_ids).toEqual(['contact'])
    expect(plans).toHaveLength(4)
  })

  it('groups competing overlapping OCR regions in one crop and preserves every ID', () => {
    const units = ['02.710.25n0', '02.710.2500'].map((text, order) => ({ ...makeSourceUnit({ page: 1, text, order, id: `contact-${order}`,
      box: { x: .1 + order * .001, y: .9, width: .4, height: .02 }, confidence: .8 }), translation_status: 'source_crop' as const }))
    expect(planRecoveryCrops(pendingLedger(units))[0].unit_ids).toEqual(['contact-0', 'contact-1'])
  })

  it('exports only JPEG regions within total budget and releases decoded images', async () => {
    const close = vi.fn(); const drawImage = vi.fn()
    vi.stubGlobal('createImageBitmap', vi.fn().mockResolvedValue({ width: 2000, height: 4000, close }))
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ drawImage } as unknown as CanvasRenderingContext2D)
    vi.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockReturnValue(`data:image/jpeg;base64,${'A'.repeat(400000)}`)
    const units = Array.from({ length: 5 }, (_, order) => ({ ...makeSourceUnit({ page: 1, text: '문의', order, id: `unit-${order}`,
      box: { x: .1, y: .1 + order * .1, width: .5, height: .03 }, confidence: .5 }), translation_status: 'source_crop' as const }))
    const regions = await recoveryCrops(pendingLedger(units), [{ page_number: 1, url: 'blob:original', file: new File(['private original'], 'notice.jpg') }])
    expect(regions).toHaveLength(3)
    expect(regions.reduce((total, region) => total + region.data_url.length, 0)).toBeLessThanOrEqual(1500000)
    expect(close).toHaveBeenCalledTimes(4)
    expect(drawImage).toHaveBeenCalledTimes(4)
    expect(regions.every((region) => region.unit_ids.length === 1 && region.data_url.startsWith('data:image/jpeg;base64,'))).toBe(true)
  })

  it('uses a bounded full-page crop when OCR returned no text', () => {
    const unit = { ...makeSourceUnit({ page: 1, text: '', order: 0 }), translation_status: 'source_crop' as const }
    expect(planRecoveryCrops(pendingLedger([unit]))[0]).toMatchObject({ unit_ids: [unit.id], box: { x: 0, y: 0, width: 1, height: 1 } })
  })
})

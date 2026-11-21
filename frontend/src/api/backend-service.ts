import { request } from './client'
import { moduleMeta } from '@/data/modules'
import type { ActionResult, EntryRow, OverviewResult, PageResult } from '@/data/types'
import type {
  DispatchResult,
  RecomputeResult,
  RevalidateResult,
  ReworkItem,
  ReworkTrace,
  ReworkView,
} from '@/domain/quality_rework'

export { moduleMeta }

export async function listEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<PageResult> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}?${query}`)
  if (!response.ok) throw new Error('业务数据读取失败')
  return await response.json()
}

export async function createEntry(
  key: string,
  values: Record<string, string>,
): Promise<ActionResult> {
  const response = await request(`/api/${key}`, {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  return await response.json()
}

export async function runAction(
  key: string,
  id: number,
  action: string,
): Promise<ActionResult> {
  const response = await request(`/api/${key}/${id}/actions`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  })
  return await response.json()
}

export async function downloadEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<void> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}/export?${query}`)
  if (!response.ok) throw new Error('业务数据导出失败')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${key}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

export async function loadOverview(): Promise<OverviewResult> {
  const response = await request('/api/overview')
  if (!response.ok) throw new Error('运营概览读取失败')
  return await response.json()
}

// ── 补值返工 ──

export async function loadReworkView(
  entityModel = 'customer',
): Promise<ReworkView> {
  const query = new URLSearchParams({ entity_model: entityModel }).toString()
  const response = await request(`/api/quality_rework/view?${query}`)
  if (!response.ok) throw new Error('返工视图读取失败')
  return await response.json()
}

export async function traceRework(id: number): Promise<ReworkTrace> {
  const response = await request(`/api/quality_rework/${id}/trace`)
  if (!response.ok) throw new Error('返工事项追溯失败')
  return await response.json()
}

export async function dispatchRework(
  itemIds: number[],
  owner: string,
): Promise<DispatchResult> {
  const response = await request('/api/quality_rework/dispatch', {
    method: 'POST',
    body: JSON.stringify({ item_ids: itemIds, owner }),
  })
  if (!response.ok) throw new Error('派发返工事项失败')
  return await response.json()
}

export async function recomputeQuality(
  entityModel: string,
  reportId: string,
): Promise<RecomputeResult> {
  const response = await request('/api/mdm_quality/recompute', {
    method: 'POST',
    body: JSON.stringify({ entity_model: entityModel, report_id: reportId }),
  })
  if (!response.ok) throw new Error('重算质量检查失败')
  return await response.json()
}

export async function supplementSourceField(
  sourceRecord: string,
  field: string,
  value: string,
): Promise<{ ok: boolean; before: string; after: string }> {
  const response = await request(`/api/source_record/${encodeURIComponent(sourceRecord)}/fields`, {
    method: 'POST',
    body: JSON.stringify({ field, value }),
  })
  if (!response.ok) throw new Error('补记原始行失败')
  return await response.json()
}

export async function revalidateRework(
  entityModel: string,
): Promise<RevalidateResult> {
  const response = await request('/api/quality_rework/revalidate', {
    method: 'POST',
    body: JSON.stringify({ entity_model: entityModel }),
  })
  if (!response.ok) throw new Error('复验返工事项失败')
  return await response.json()
}

export async function loadReportRework(reportId: string): Promise<{
  report_id: string
  items: ReworkItem[]
  closed_items: ReworkItem[]
}> {
  const response = await request(`/api/quality_rework/reports/${encodeURIComponent(reportId)}`)
  if (!response.ok) throw new Error('报告返工回查失败')
  return await response.json()
}

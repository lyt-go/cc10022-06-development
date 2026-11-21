/** 补值返工视图的纯前端数据层：类型、状态词和展示分组，不碰网络。 */

export type ReworkItem = {
  id: number
  返工编号: string
  统计编号: string
  实体模型: string
  来源系统: string
  来源记录: string
  源记录: string
  字段: string
  待补字段: string
  缺失字段: string
  原始值: string
  原始记录: Record<string, unknown>
  原始数据: Record<string, unknown>
  分区: string
  分区状态: string
  负责人: string
  状态: string
  可派发: boolean
  已关闭: boolean
  轮次: number
  首次轮次?: number
  最近轮次?: number
  发现时间?: string
  更新时间?: string
  关闭时间?: string
  关闭方式?: string
  关闭原因?: string
  复验值?: string
}

export type ReworkPartition = {
  分区: string
  分区状态: string
  事项数: number
  待派发: number
  已派发: number
  已关闭: number
  可派发: number
  待补字段: string[]
  来源记录: string[]
  负责人: string[]
  items: ReworkItem[]
}

export type FieldSummary = {
  字段: string
  事项数: number
  来源记录: string[]
  负责人: string[]
  事项编号: number[]
}

export type ReworkView = {
  entity_model: string
  summary: Record<string, number>
  partitions: ReworkPartition[]
  verified_partitions: ReworkPartition[]
  unverified_partitions: ReworkPartition[]
  dispatchable_fields: FieldSummary[]
  verified_pending_fields: FieldSummary[]
  items: ReworkItem[]
}

export type ReworkTrace = {
  item: ReworkItem
  返工编号: string
  统计编号: string
  来源记录: string
  待补字段: string
  原始值: string
  原始数据: Record<string, unknown>
  当前原始行: Record<string, unknown> | null
  当前字段值: string
  分区: string
  分区状态: string
  负责人: string
  状态: string
  可派发: boolean
  轮次: number
  关闭方式?: string
  关闭原因?: string
  复验值?: string
}

export type RecomputeResult = {
  ok: boolean
  completeness_pct?: number
  round?: number
  rework?: {
    新增明细: number
    更新明细: number
    同轮去重: number
    跳过已关闭: number
    跳过旧报告?: number
    待办明细: number
    可派发明细: number
  }
  partitions?: string[]
  rework_items?: ReworkItem[]
}

export type DispatchResult = {
  ok: boolean
  dispatched: ReworkItem[]
  rejected: { id: number; reason: string }[]
  dispatched_count: number
  rejected_count: number
}

export type RevalidateResult = {
  closed: number
  still_open: number
  unmatched: number
  closed_ids: number[]
  still_open_ids: number[]
  unmatched_ids: number[]
}

export function itemStatusTone(item: ReworkItem): 'open' | 'dispatched' | 'closed' | 'blocked' {
  if (item.已关闭 || item.状态 === '已关闭' || item.状态 === '作废') return 'closed'
  if (item.状态 === '已派发') return 'dispatched'
  if (item.分区状态 === '未核分区') return 'blocked'
  return 'open'
}

/** 值班视图只把已核分区、待派发的字段算作可交给人的事项。 */
export function dispatchableItems(view: ReworkView): ReworkItem[] {
  return view.items.filter((item) => item.可派发)
}

export function blockingReason(item: ReworkItem): string {
  if (item.已关闭) return '已关闭'
  if (item.分区状态 === '未核分区') return '所在分区尚未核验'
  if (item.状态 === '已派发') return '已派发'
  if (!item.负责人) return '待指定负责人'
  return ''
}

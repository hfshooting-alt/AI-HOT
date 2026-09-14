export function collectionLabel(source: { status: string; reasonCode?: string }): string {
  const labels: Record<string, string> = {
    not_started_budget: "费用熔断后未启动",
    budget_stopped: "费用止损",
    identity_mismatch: "来源身份未核实",
    list_not_loaded: "文章列表未加载",
    detail_time_unavailable: "发布时间未核实",
    boundary_unverified: "时间窗口未扫完",
    content_incomplete: "部分正文未取得",
  };
  const reason = labels[source.reasonCode || ""];
  if (source.status === "partial") return `部分完成${reason ? `：${reason}` : "，覆盖不完整"}`;
  if (source.status === "not_requested") return "未启用";
  if (source.status === "complete") return "完成";
  return reason || "采集未完成，原因待核实";
}

/* 运营报表：趋势、结构、社区对比与导出 */

import { api } from "../api.js";
import { store } from "../store.js";
import {
  icon, esc, fmtMoney, fmtNum, fmtDateTime, fmtPct, statusMeta, emptyState, toast, setBusy, downloadBlob,
} from "../ui.js";
import { comboChart, donutChart, horizontalBars } from "../charts.js";

const STATUS_COLORS = {
  completed: "#0e9f6e",
  charging: "#0ea5a4",
  reserved: "#7c5cfc",
  pending_payment: "#f59e0b",
  cancelled: "#94a3b8",
  abnormal: "#ef4444",
};

export async function render(page, ctx) {
  const days = [7, 30, 90].includes(Number(ctx.query.days)) ? Number(ctx.query.days) : 30;
  const communityId = store.state.currentCommunityId;
  const data = await api.reports(days, communityId);
  const summary = data.summary;

  const statusItems = (data.order_status || []).map((row) => ({
    key: row.key,
    label: statusMeta(row.key).label,
    value: row.value,
    color: STATUS_COLORS[row.key] || "#94a3b8",
  }));
  const donutTotal = statusItems.reduce((sum, item) => sum + item.value, 0);
  const donut = statusItems.length
    ? donutChart(statusItems, { size: 150, thickness: 16, centerValue: fmtNum(donutTotal), centerLabel: "订单总数" })
    : `<div class="chart-empty">暂无订单</div>`;
  const legend = statusItems
    .map(
      (item) => `<div class="legend-item"><span class="legend-dot" style="background:${item.color}"></span>${esc(item.label)} <b style="color:var(--ink-2)">${fmtNum(item.value)}</b></div>`
    )
    .join("");

  const labels = data.trend.map((row) => row.date.slice(5));
  const trend = comboChart({
    labels,
    bars: data.trend.map((row) => row.orders),
    barLabel: "订单",
    line: data.trend.map((row) => row.revenue),
    lineLabel: "收入",
    height: 270,
  });

  const paymentMap = { wechat: "微信支付", alipay: "支付宝", balance: "余额支付" };
  const paymentBars = horizontalBars(
    (data.payment_methods || []).map((row) => ({ label: paymentMap[row.key] || row.key, value: row.value })),
    { valueFormatter: (value) => `${fmtNum(value)} 笔` }
  );

  const communityRows = (data.communities || [])
    .map(
      (row) => `<tr>
        <td class="strong nowrap">${esc(row.name)}</td>
        <td>${row.pile_count} 台</td>
        <td>${fmtPct(row.availability)}</td>
        <td>${fmtPct(row.utilization)}</td>
        <td class="num">${fmtNum(row.order_count)}</td>
        <td class="num">${fmtNum(row.energy_kwh, 1)} kWh</td>
        <td class="num strong">¥${fmtMoney(row.revenue)}</td>
        <td class="num" style="color:${row.fault_rate ? "#be123c" : "var(--muted)"}">${fmtPct(row.fault_rate)}</td>
        <td class="num">${row.pending_tickets}</td>
      </tr>`
    )
    .join("");

  page.innerHTML = `
    <div class="page-head">
      <div>
        <span class="eyebrow">数据分析</span>
        <h1>运营报表</h1>
        <p class="sub">${esc(store.communityName())} · 设备可用率、利用率、收入、退款与社区对比</p>
      </div>
      <div class="page-actions">
        <div class="segmented" id="report-range">
          <button data-days="7" class="${days === 7 ? "active" : ""}">7 天</button>
          <button data-days="30" class="${days === 30 ? "active" : ""}">30 天</button>
          <button data-days="90" class="${days === 90 ? "active" : ""}">90 天</button>
        </div>
        <button class="btn btn-primary btn-sm" id="report-export">${icon("download", 14)} 导出订单</button>
      </div>
    </div>
    <div class="mini-stats">
      <div class="mini-stat"><span>周期收入</span><b>¥${fmtMoney(summary.revenue)} <small>元</small></b></div>
      <div class="mini-stat"><span>完成订单</span><b>${fmtNum(summary.completed_orders)} <small>笔</small></b></div>
      <div class="mini-stat"><span>客单价</span><b>¥${fmtMoney(summary.avg_order_amount)} <small>元</small></b></div>
      <div class="mini-stat"><span>退款金额</span><b style="color:#be123c">¥${fmtMoney(summary.refund)} <small>元</small></b></div>
    </div>
    <div class="grid grid-dash">
      <section class="card">
        <div class="card-head"><div><h3>订单与收入趋势</h3><p>近 ${days} 天 · 柱：订单量 / 线：完成收入</p></div><span class="badge badge-green no-dot">${esc(fmtDateTime(data.updated_at))}</span></div>
        <div class="card-body" style="padding-top:12px">${trend}</div>
      </section>
      <section class="card">
        <div class="card-head"><div><h3>订单状态结构</h3><p>按订单数统计</p></div></div>
        <div class="card-body">
          <div class="donut-wrap">${donut}<div class="legend" style="flex-direction:column;gap:8px;margin:0">${legend || `<span class="muted">暂无数据</span>`}</div></div>
          <div class="section-label">支付方式</div>
          ${paymentBars || `<span class="muted" style="font-size:12px">暂无已完成订单</span>`}
        </div>
      </section>
    </div>
    <section class="card" style="margin-top:16px">
      <div class="card-head"><div><h3>社区运营对比</h3><p>收入、可用率与工单积压 · 覆盖 ${data.communities.length} 个社区</p></div></div>
      <div class="card-body" style="padding-top:10px">
        <div class="table-wrap"><table class="data">
          <thead><tr><th>社区</th><th>设备</th><th>可用率</th><th>利用率</th><th class="num">订单</th><th class="num">电量</th><th class="num">收入</th><th class="num">故障率</th><th class="num">工单</th></tr></thead>
          <tbody>${communityRows || `<tr><td colspan="9">${emptyState("chart", "暂无社区数据")}</td></tr>`}</tbody>
        </table></div>
      </div>
    </section>
    <div class="grid grid-2" style="margin-top:16px">
      <section class="card">
        <div class="card-head"><div><h3>社区收入分布</h3><p>按完成订单收入排序</p></div></div>
        <div class="card-body" style="padding-top:12px">
          ${horizontalBars(
            (data.communities || []).map((row) => ({ label: row.name, value: row.revenue })),
            { valueFormatter: (value) => `¥${fmtNum(value)}` }
          )}
        </div>
      </section>
      <section class="card">
        <div class="card-head"><div><h3>指标口径</h3><p>报表指标定义与计算方式</p></div></div>
        <div class="card-body" style="padding-top:12px">
          <div class="rule-list">
            <div class="rule-item">${icon("info", 14)} 可用率 = 在线且状态正常的设备 / 设备总数。</div>
            <div class="rule-item">${icon("info", 14)} 利用率 = 正在充电的枪口 / 全部枪口。</div>
            <div class="rule-item">${icon("info", 14)} 客单价 = 完成订单收入 / 完成订单数。</div>
            <div class="rule-item">${icon("info", 14)} 退款金额包含已完成与异常订单的退款。</div>
          </div>
        </div>
      </section>
    </div>
    <div class="muted" style="font-size:10.5px;margin-top:16px;text-align:right">报表数据来自业务库实时聚合 · 导出上限 5000 行</div>`;

  document.querySelectorAll("#report-range button").forEach((button) => {
    button.addEventListener("click", () => {
      location.hash = `#/reports?days=${button.dataset.days}`;
    });
  });
  document.getElementById("report-export").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    setBusy(button, true, "导出中…");
    try {
      const params = new URLSearchParams({ days: String(days) });
      if (communityId) params.set("community_id", String(communityId));
      const { blob, filename } = await api.download(`/api/reports/orders.csv?${params}`);
      downloadBlob(blob, filename);
      toast("订单数据已导出", "success");
    } catch (error) {
      toast(error.message, "error");
    } finally {
      setBusy(button, false);
    }
  });
}

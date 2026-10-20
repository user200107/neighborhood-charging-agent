/* 运营总览 */

import { api } from "../api.js";
import { store } from "../store.js";
import {
  icon, esc, fmtMoney, fmtNum, fmtDateTime, fmtRelative, greeting, todayLabel,
  statusBadge, priorityBadge, emptyState,
} from "../ui.js";
import { comboChart, donutChart, horizontalBars } from "../charts.js";

const KPI_ICONS = {
  availability: "activity",
  utilization: "bolt",
  revenue: "trend",
  mttr: "clock",
  fault_rate: "alert",
  reservation_success: "checkCircle",
};

const FAULT_LABELS = {
  temperature: "温度异常",
  fault: "设备故障",
  offline: "设备离线",
  interrupted: "充电中断",
  power: "功率异常",
};

function formatKpi(card) {
  if (card.unit === "%") return Number(card.value || 0).toFixed(1);
  if (card.unit === "元") return `¥${fmtMoney(card.value)}`;
  if (card.unit === "小时") return `${Number(card.value).toFixed(1)}<small>小时</small>`;
  return fmtNum(card.value);
}

export async function render(page, ctx) {
  const days = Math.min(30, Math.max(1, Number(ctx.query.days) || 7));
  const data = await api.dashboard(days, store.state.currentCommunityId);
  const summary = data.summary;
  store.setPendingApprovals(summary.pending_approvals || 0);
  const communityName = store.communityName();
  const firstName = store.user.display_name;

  const kpis = data.cards
    .map(
      (card) => `<article class="kpi tone-${esc(card.tone || "emerald")}">
        <div class="kpi-top">
          <span class="kpi-ico">${icon(KPI_ICONS[card.key] || "chart", 16)}</span>
          <span class="kpi-label">${esc(card.label)}</span>
        </div>
        <div class="kpi-value">${formatKpi(card)}${card.unit === "%" || card.unit === "元" ? `<small>${esc(card.unit)}</small>` : ""}</div>
        <div class="kpi-hint" title="${esc(card.hint)}">${esc(card.hint)}</div>
      </article>`
    )
    .join("");

  const alerts = (data.alerts || [])
    .map(
      (alert) => `<div class="alert-item ${esc(alert.level)}">
        <span class="a-ico">${icon(alert.level === "critical" ? "alert" : alert.level === "info" ? "info" : "clock", 15)}</span>
        <div><b>${esc(alert.title)}</b> <span>${esc(alert.detail)}</span></div>
        <a href="${esc(alert.link)}">${icon("arrowRight", 13)} 去处理</a>
      </div>`
    )
    .join("");

  const labels = data.trend.map((row) => row.date.slice(5));
  const trendChart = comboChart({
    labels,
    bars: data.trend.map((row) => row.orders),
    barLabel: "订单",
    line: data.trend.map((row) => row.revenue),
    lineLabel: "收入",
    height: 250,
  });

  const donutTotal = data.pile_status.reduce((sum, item) => sum + item.value, 0);
  const donut = donutChart(data.pile_status, {
    size: 156,
    thickness: 15,
    centerValue: fmtNum(donutTotal),
    centerLabel: "设备总数",
  });
  const legend = data.pile_status
    .map(
      (item) => `<div class="legend-item"><span class="legend-dot" style="background:${item.color}"></span>${esc(item.label)} <b style="color:var(--ink-2)">${fmtNum(item.value)}</b></div>`
    )
    .join("");

  const communityBars = horizontalBars(
    data.communities.map((community) => ({ label: community.name, value: community.revenue })),
    { valueFormatter: (value) => `¥${fmtNum(value)}` }
  );

  const topFaults = (data.top_faults || []).length
    ? data.top_faults
        .map(
          (fault) => `<div class="row-between" style="padding:8px 0;border-bottom:1px dashed var(--line)">
            <div class="row" style="gap:8px">
              <span class="badge badge-red no-dot">${icon("alert", 12)}</span>
              <div><b style="font-size:12px">${esc(fault.pile_code)}</b><div class="muted" style="font-size:10.5px">${esc(FAULT_LABELS[fault.event_type] || fault.event_type)} · ${fault.count} 次</div></div>
            </div>
            <span class="muted" style="font-size:10.5px">${esc(fmtRelative(fault.last_at))}</span>
          </div>`
        )
        .join("")
    : `<div class="muted" style="font-size:12px;padding:12px 0">近 ${days} 天未发现严重设备告警。</div>`;

  const recentTickets = (data.recent_tickets || []).length
    ? data.recent_tickets
        .map(
          (ticket) => `<tr>
            <td>${priorityBadge(ticket.priority)}</td>
            <td><a href="#/tickets?id=${ticket.id}" class="strong" style="color:var(--ink)">${esc(ticket.title)}</a><span class="subline">${esc(ticket.pile_code || "未关联设备")} · ${esc(ticket.community_name || "")}</span></td>
            <td>${statusBadge(ticket.status)}</td>
            <td class="nowrap muted">${esc(ticket.age_text)}</td>
            <td class="nowrap muted">${esc(fmtDateTime(ticket.created_at))}</td>
          </tr>`
        )
        .join("")
    : `<tr><td colspan="5">${emptyState("checkCircle", "暂无工单", "当前没有需要处理的维修工单。")}</td></tr>`;

  const recentOrders = (data.recent_orders || []).length
    ? data.recent_orders
        .map(
          (order) => `<tr>
            <td><span class="mono" style="font-size:11px">${esc(order.order_no)}</span><span class="subline">${esc(order.community_name || "")}</span></td>
            <td>${esc(order.pile_code || "—")}<span class="subline">${esc(order.user_name || "")}</span></td>
            <td>${statusBadge(order.status)}</td>
            <td class="num">${order.status === "completed" || order.status === "charging" ? `${fmtNum(order.energy_kwh, 1)} kWh` : "—"}</td>
            <td class="num strong">¥${fmtMoney(order.amount)}</td>
            <td class="nowrap muted">${esc(fmtDateTime(order.created_at))}</td>
          </tr>`
        )
        .join("")
    : `<tr><td colspan="6">${emptyState("order", "暂无订单", "近期的充电订单会展示在这里。")}</td></tr>`;

  page.innerHTML = `
    <div class="page-head">
      <div>
        <span class="eyebrow">${todayLabel()}</span>
        <h1>${greeting()}，${esc(firstName)}</h1>
        <p class="sub">${esc(communityName)} · 近 ${days} 天运营概况${summary.overdue_tickets ? ` · <b style="color:#b45309">${summary.overdue_tickets} 张工单 SLA 超时</b>` : ""}</p>
      </div>
      <div class="page-actions">
        <div class="segmented" id="dash-range">
          <button data-days="1" class="${days === 1 ? "active" : ""}">今日</button>
          <button data-days="7" class="${days === 7 ? "active" : ""}">7 天</button>
          <button data-days="30" class="${days === 30 ? "active" : ""}">30 天</button>
        </div>
        <button class="btn btn-ghost btn-sm" id="dash-refresh">${icon("refresh", 14)} 刷新</button>
        ${store.can("agent") ? `<a class="btn btn-primary btn-sm" href="#/agent">${icon("agent", 14)} 问 Agent</a>` : ""}
      </div>
    </div>
    ${alerts ? `<div class="alert-strip">${alerts}</div>` : ""}
    <div class="kpi-grid">${kpis}</div>
    <div class="grid grid-dash">
      <section class="card">
        <div class="card-head">
          <div><h3>订单与收入趋势</h3><p>每日订单量（柱）与完成收入（线），单位：笔 / 元</p></div>
          <span class="badge badge-green no-dot">近 ${days} 天</span>
        </div>
        <div class="card-body" style="padding-top:12px">${trendChart}</div>
      </section>
      <section class="card">
        <div class="card-head"><div><h3>设备状态分布</h3><p>在线、充电、故障与维护</p></div><span class="muted" style="font-size:11px">${fmtNum(summary.total_piles)} 台桩</span></div>
        <div class="card-body">
          <div class="donut-wrap">
            ${donut}
            <div class="legend" style="flex-direction:column;gap:9px;margin:0">${legend}</div>
          </div>
          <div class="stat-row">
            <div class="stat-mini"><b>${fmtNum(summary.total_connectors)}</b><span>枪口总数</span></div>
            <div class="stat-mini"><b>${fmtNum(summary.charging_connectors)}</b><span>正在充电</span></div>
            <div class="stat-mini"><b>${fmtNum(summary.active_reservations)}</b><span>有效预约</span></div>
          </div>
        </div>
      </section>
    </div>
    <div class="grid grid-dash-bottom" style="margin-top:16px">
      <section class="card">
        <div class="card-head"><div><h3>最新工单</h3><p>按创建时间排序 · 点击查看处理详情</p></div><a class="btn btn-ghost btn-sm" href="#/tickets">全部工单 ${icon("arrowRight", 13)}</a></div>
        <div class="card-body" style="padding-top:10px">
          <div class="table-wrap"><table class="data">
            <thead><tr><th>优先级</th><th>工单</th><th>状态</th><th>已持续</th><th>创建时间</th></tr></thead>
            <tbody>${recentTickets}</tbody>
          </table></div>
        </div>
      </section>
      <div class="stack">
        <section class="card">
          <div class="card-head"><div><h3>社区收入对比</h3><p>近 ${days} 天完成订单收入</p></div><a class="btn btn-ghost btn-sm" href="#/reports">报表 ${icon("arrowRight", 13)}</a></div>
          <div class="card-body" style="padding-top:12px">${communityBars || emptyState("chart", "暂无社区数据")}</div>
        </section>
        <section class="card">
          <div class="card-head"><div><h3>高频故障</h3><p>近 ${days} 天 warning / critical 事件</p></div></div>
          <div class="card-body" style="padding-top:8px">${topFaults}</div>
        </section>
      </div>
    </div>
    <section class="card" style="margin-top:16px">
      <div class="card-head"><div><h3>最近订单</h3><p>跨社区实时订单流水</p></div><a class="btn btn-ghost btn-sm" href="#/orders">全部订单 ${icon("arrowRight", 13)}</a></div>
      <div class="card-body" style="padding-top:10px">
        <div class="table-wrap"><table class="data">
          <thead><tr><th>订单</th><th>设备 / 用户</th><th>状态</th><th style="text-align:right">电量</th><th style="text-align:right">金额</th><th>创建时间</th></tr></thead>
          <tbody>${recentOrders}</tbody>
        </table></div>
      </div>
    </section>
    <div class="muted" style="font-size:10.5px;margin-top:16px;text-align:right">数据更新于 ${esc(fmtDateTime(data.updated_at))} · trace_id 已随请求记录</div>`;

  document.getElementById("dash-refresh").addEventListener("click", () => ctx.refresh());
  document.querySelectorAll("#dash-range button").forEach((button) => {
    button.addEventListener("click", () => {
      location.hash = `#/dashboard?days=${button.dataset.days}`;
    });
  });
}

/* 审计日志：安全留痕查询 */

import { api } from "../api.js";
import { store } from "../store.js";
import {
  icon, esc, fmtDateTime, fmtNum, emptyState, openModal, debounce, renderPagination,
} from "../ui.js";

const ACTION_LABELS = {
  login: "登录成功",
  "auth.login": "登录成功",
  "auth.login_failed": "登录失败",
  "auth.logout": "退出登录",
  "auth.refresh": "令牌续期",
  "auth.password_changed": "修改密码",
  "agent.chat": "Agent 对话",
  "order.created": "订单创建",
  "order.started": "开始充电",
  "order.completed": "订单完成",
  "order.cancelled": "订单取消",
  "reservation.cancelled": "预约取消",
  "ticket.created": "工单创建",
  "ticket.assigned": "工单分派",
  "ticket.accepted": "维修接单",
  "ticket.started": "开始维修",
  "ticket.resolved": "维修回填",
  "ticket.verified": "测试订单验收",
  "ticket.closed": "工单关闭",
  "ticket.cancelled": "工单取消",
  "ticket.escalated": "故障升级",
  "device_event.received": "设备事件接入",
  "approval.created": "审批创建",
  "approval.approved": "审批通过",
  "approval.rejected": "审批驳回",
  "approval.executed": "审批执行",
  "approval.execution_failed": "审批执行失败",
  "user.created": "用户创建",
  "user.updated": "用户更新",
};

export async function render(page, ctx) {
  const action = ctx.query.action || "";
  const result = ctx.query.result || "";
  const keyword = ctx.query.keyword || "";
  const pageNo = Math.max(1, Number(ctx.query.page) || 1);
  const [actions, list] = await Promise.all([
    api.auditActions(),
    api.audit({
      action: action || undefined,
      result: result || undefined,
      keyword: keyword || undefined,
      page: pageNo,
      page_size: 20,
    }),
  ]);

  const rows = list.items
    .map(
      (log) => `<tr data-audit="${log.id}" style="cursor:pointer">
        <td class="nowrap muted">${esc(fmtDateTime(log.created_at))}</td>
        <td>${esc(log.actor_name)}<span class="subline">${esc(log.actor_role)}</span></td>
        <td><span class="badge ${log.result === "success" ? "badge-green" : "badge-red"} no-dot">${esc(ACTION_LABELS[log.action] || log.action)}</span></td>
        <td>${esc(log.resource_type || "—")}<span class="subline mono">${esc(log.resource_id || "")}</span></td>
        <td class="mono" style="font-size:10px">${esc(log.trace_id || "—")}</td>
        <td>${log.ip ? esc(log.ip) : "—"}</td>
        <td>${icon("chevronRight", 14)}</td>
      </tr>`
    )
    .join("");

  page.innerHTML = `
    <div class="page-head">
      <div>
        <span class="eyebrow">安全合规</span>
        <h1>审计日志</h1>
        <p class="sub">登录、权限拒绝、设备事件、订单、工单、审批与 Agent 工具调用全链路留痕</p>
      </div>
      <div class="page-actions"><span class="badge badge-slate no-dot">${icon("lock", 12)} 仅管理员可见</span></div>
    </div>
    <div class="toolbar">
      <div class="input-icon">${icon("search", 16)}<input class="input" id="audit-search" placeholder="搜索操作人、资源编号或 trace_id…" value="${esc(keyword)}" /></div>
      <select class="select" id="audit-action">
        <option value="">全部动作</option>
        ${actions.items.map((item) => `<option value="${esc(item)}" ${action === item ? "selected" : ""}>${esc(ACTION_LABELS[item] || item)}</option>`).join("")}
      </select>
      <select class="select" id="audit-result">
        <option value="">全部结果</option>
        <option value="success" ${result === "success" ? "selected" : ""}>成功</option>
        <option value="failed" ${result === "failed" ? "selected" : ""}>失败</option>
      </select>
      <div class="toolbar-spacer"></div>
      <span class="muted" style="font-size:11px">共 ${fmtNum(list.total)} 条记录 · 保留周期 180 天</span>
    </div>
    <section class="card">
      <div class="table-wrap"><table class="data">
        <thead><tr><th>时间</th><th>操作人</th><th>动作</th><th>资源</th><th>trace_id</th><th>IP</th><th></th></tr></thead>
        <tbody>${rows || `<tr><td colspan="7">${emptyState("audit", "没有审计记录", "调整筛选条件，或等待新的操作产生。")}</td></tr>`}</tbody>
      </table></div>
    </section>
    <div class="table-foot" id="audit-pagination"></div>
    <div class="warning-box" style="margin-top:16px;display:flex;gap:8px">${icon("shield", 15)}<div>审计日志只读，不支持前端修改或删除。生产环境应配置独立存储、访问控制与防篡改策略。</div></div>`;

  renderPagination(document.getElementById("audit-pagination"), list, (nextPage) => {
    const params = new URLSearchParams();
    if (action) params.set("action", action);
    if (result) params.set("result", result);
    if (keyword) params.set("keyword", keyword);
    params.set("page", String(nextPage));
    location.hash = `#/audit?${params}`;
  });

  document.getElementById("audit-action").addEventListener("change", (event) => {
    const params = new URLSearchParams();
    if (event.target.value) params.set("action", event.target.value);
    if (result) params.set("result", result);
    if (keyword) params.set("keyword", keyword);
    location.hash = `#/audit${params.size ? `?${params}` : ""}`;
  });
  document.getElementById("audit-result").addEventListener("change", (event) => {
    const params = new URLSearchParams();
    if (action) params.set("action", action);
    if (event.target.value) params.set("result", event.target.value);
    if (keyword) params.set("keyword", keyword);
    location.hash = `#/audit${params.size ? `?${params}` : ""}`;
  });
  const search = document.getElementById("audit-search");
  search.addEventListener(
    "input",
    debounce(() => {
      const params = new URLSearchParams();
      if (action) params.set("action", action);
      if (result) params.set("result", result);
      if (search.value.trim()) params.set("keyword", search.value.trim());
      location.hash = `#/audit${params.size ? `?${params}` : ""}`;
    }, 450)
  );

  const byId = new Map(list.items.map((log) => [log.id, log]));
  page.querySelectorAll("[data-audit]").forEach((row) => {
    row.addEventListener("click", () => {
      const log = byId.get(Number(row.dataset.audit));
      if (!log) return;
      openModal({
        title: "审计详情",
        subtitle: `${ACTION_LABELS[log.action] || log.action} · ${fmtDateTime(log.created_at)}`,
        size: "modal-lg",
        body: `<div class="info-grid">
            <div class="info-item"><span>操作人</span><b>${esc(log.actor_name)} · ${esc(log.actor_role)}</b></div>
            <div class="info-item"><span>结果</span><b>${log.result === "success" ? "成功" : "失败"}</b></div>
            <div class="info-item"><span>资源</span><b>${esc(log.resource_type || "—")} / ${esc(log.resource_id || "—")}</b></div>
            <div class="info-item"><span>IP</span><b>${esc(log.ip || "—")}</b></div>
            <div class="info-item span-2"><span>trace_id</span><b class="mono">${esc(log.trace_id || "—")}</b></div>
          </div>
          <div class="section-label">详情</div>
          <pre style="background:var(--surface-2);border:1px solid var(--line);border-radius:10px;padding:14px;font-family:var(--mono);font-size:11px;line-height:1.7;overflow:auto;white-space:pre-wrap">${esc(JSON.stringify(log.detail || {}, null, 2))}</pre>`,
        footer: `<button class="btn btn-ghost" data-close>关闭</button>`,
      });
    });
  });
}

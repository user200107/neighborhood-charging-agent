/* 审批中心：申请、决策、执行与回执 */

import { api } from "../api.js";
import { store } from "../store.js";
import {
  icon, esc, fmtDateTime, fmtMoney, fmtNum, statusBadge, emptyState, openDrawer, openModal,
  confirmAction, toast, renderPagination, setBusy,
} from "../ui.js";

const TYPES = [
  { key: "", label: "全部类型" },
  { key: "stop_pile", label: "设备停机" },
  { key: "refund", label: "订单退款" },
  { key: "price_change", label: "计费调价" },
  { key: "bulk_reassign", label: "批量改派" },
];

const TABS = [
  { key: "pending", label: "待审批" },
  { key: "approved", label: "已通过" },
  { key: "executed", label: "已执行" },
  { key: "rejected", label: "已驳回" },
  { key: "", label: "全部" },
];

const TYPE_ICONS = {
  stop_pile: "stop",
  refund: "order",
  price_change: "bolt",
  bulk_reassign: "users",
};

function canDecide() {
  return ["admin", "finance"].includes(store.user.role);
}

export async function render(page, ctx) {
  const status = ctx.query.status === undefined ? "pending" : ctx.query.status;
  const type = ctx.query.type || "";
  const pageNo = Math.max(1, Number(ctx.query.page) || 1);
  const communityId = store.state.currentCommunityId;

  const [summary, list] = await Promise.all([
    api.approvalSummary(),
    api.approvals({
      community_id: communityId || undefined,
      status: status || undefined,
      type: type || undefined,
      page: pageNo,
      page_size: 12,
    }),
  ]);
  store.setPendingApprovals(summary.pending || 0);
  const byId = new Map(list.items.map((item) => [item.id, item]));

  const tabs = TABS.map(
    (tab) => `<button class="tab ${status === tab.key ? "active" : ""}" data-status="${tab.key}">${tab.label}${tab.key === "pending" && summary.pending ? `<span class="count">${summary.pending}</span>` : ""}</button>`
  ).join("");

  const rows = list.items
    .map(
      (approval) => `<tr>
        <td><span class="kpi-ico" style="width:30px;height:30px;display:inline-grid;margin-right:8px;vertical-align:middle;background:var(--surface-3);color:var(--ink-2)">${icon(TYPE_ICONS[approval.type] || "shield", 15)}</span><span class="strong">${esc(approval.type_label)}</span><span class="subline mono">${esc(approval.approval_no)}</span></td>
        <td>${esc(approval.target_name || approval.target_id)}<span class="subline">${esc(approval.impact_scope || "")}</span></td>
        <td>${esc(approval.requester?.display_name || "—")}<span class="subline">${esc(approval.community_name || "")}</span></td>
        <td class="num strong">${approval.amount ? `¥${fmtMoney(approval.amount)}` : "—"}</td>
        <td>${statusBadge(approval.status, "", "approval")}</td>
        <td class="nowrap muted">${esc(fmtDateTime(approval.created_at))}<span class="subline">${esc(approval.source === "agent" ? "Agent 发起" : "人工发起")}</span></td>
        <td><div class="table-actions">${canDecide() && approval.status === "pending" ? `<button class="btn btn-soft btn-sm" data-approval-action="decide" data-id="${approval.id}">审批</button>` : ""}${canDecide() && approval.status === "approved" ? `<button class="btn btn-primary btn-sm" data-approval-action="execute" data-id="${approval.id}">执行</button>` : ""}<button class="btn btn-ghost btn-sm" data-approval-action="detail" data-id="${approval.id}">详情</button></div></td>
      </tr>`
    )
    .join("");

  page.innerHTML = `
    <div class="page-head">
      <div>
        <span class="eyebrow">风险控制</span>
        <h1>审批中心</h1>
        <p class="sub">${esc(store.communityName())} · 停机、退款、调价、批量改派必须经人工审批后执行</p>
      </div>
      <div class="page-actions">
        <span class="badge badge-amber no-dot">${icon("shield", 12)} 高风险动作不直接执行</span>
      </div>
    </div>
    <div class="mini-stats">
      <div class="mini-stat"><span>待审批</span><b style="color:#a16207">${fmtNum(summary.pending)} <small>条</small></b></div>
      <div class="mini-stat"><span>已通过待执行</span><b>${fmtNum(summary.approved)} <small>条</small></b></div>
      <div class="mini-stat"><span>已执行</span><b style="color:#087a54">${fmtNum(summary.executed)} <small>条</small></b></div>
      <div class="mini-stat"><span>已驳回 / 失败</span><b>${fmtNum((summary.rejected || 0) + (summary.failed || 0))} <small>条</small></b></div>
    </div>
    <div class="tabs">${tabs}</div>
    <div class="toolbar">
      <select class="select" id="type-filter">
        ${TYPES.map((item) => `<option value="${item.key}" ${type === item.key ? "selected" : ""}>${item.label}</option>`).join("")}
      </select>
      <div class="toolbar-spacer"></div>
      <span class="muted" style="font-size:11px">审批与执行均写入审计，禁止重复审批和重复执行</span>
    </div>
    <section class="card">
      <div class="table-wrap"><table class="data">
        <thead><tr><th>类型 / 单号</th><th>目标与影响</th><th>申请人</th><th style="text-align:right">金额</th><th>状态</th><th>提交时间</th><th style="text-align:right">操作</th></tr></thead>
        <tbody>${rows || `<tr><td colspan="7">${emptyState("approval", "暂无审批记录", status === "pending" ? "当前没有待决策的高风险动作。" : "审批记录会展示在这里。")}</td></tr>`}</tbody>
      </table></div>
    </section>
    <div class="table-foot" id="approval-pagination"></div>
    <div class="warning-box" style="margin-top:16px;display:flex;gap:8px">${icon("shield", 15)}<div>安全策略：Agent 与运营人员的停机、退款、调价、批量改派请求只创建审批单；审批人与执行人由财务/管理员担任，执行结果回写审批与审计日志。</div></div>`;

  renderPagination(document.getElementById("approval-pagination"), list, (nextPage) => {
    const params = new URLSearchParams();
    params.set("status", status);
    if (type) params.set("type", type);
    params.set("page", String(nextPage));
    location.hash = `#/approvals?${params}`;
  });

  document.querySelectorAll("[data-status]").forEach((tab) => {
    tab.addEventListener("click", () => {
      const params = new URLSearchParams();
      params.set("status", tab.dataset.status);
      if (type) params.set("type", type);
      location.hash = `#/approvals?${params}`;
    });
  });
  document.getElementById("type-filter").addEventListener("change", (event) => {
    const params = new URLSearchParams();
    params.set("status", status);
    if (event.target.value) params.set("type", event.target.value);
    location.hash = `#/approvals?${params}`;
  });
  page.querySelectorAll("[data-approval-action]").forEach((button) => {
    button.addEventListener("click", () => {
      const approval = byId.get(Number(button.dataset.id));
      if (!approval) return;
      if (button.dataset.approvalAction === "detail") openApprovalDetail(approval.id, ctx);
      else if (button.dataset.approvalAction === "decide") openDecideModal(approval, ctx);
      else if (button.dataset.approvalAction === "execute") openExecuteConfirm(approval, ctx, button);
    });
  });

  if (ctx.query.id) openApprovalDetail(Number(ctx.query.id), ctx);
}

function openDecideModal(approval, ctx) {
  const { root } = openModal({
    title: "审批决策",
    subtitle: `${approval.approval_no} · ${approval.type_label}`,
    body: `<div class="warning-box">${icon("alert", 14)} ${esc(approval.impact_scope || "")}${approval.amount ? ` · 金额 ¥${fmtMoney(approval.amount)}` : ""}</div>
      <div class="section-label">申请理由</div>
      <div class="quote">${esc(approval.reason)}</div>
      <div class="field" style="margin-top:16px"><label for="decision-comment">审批意见（可选）</label><textarea class="textarea" id="decision-comment" placeholder="记录核实情况、限制条件或驳回原因。"></textarea></div>
      <div class="hint" style="margin-top:8px">审批后仍需在详情中执行；执行前可再次核对影响范围。</div>`,
    footer: `<button class="btn btn-ghost" data-close>取消</button><button class="btn btn-danger-soft" id="reject-btn">驳回</button><button class="btn btn-primary" id="approve-btn">通过</button>`,
    onMount: (modal, closeFn) => {
      const decide = async (decision, button) => {
        setBusy(button, true, decision === "approve" ? "通过中…" : "驳回中…");
        try {
          await api.decideApproval(approval.id, decision, modal.querySelector("#decision-comment").value.trim());
          closeFn();
          toast(decision === "approve" ? "审批已通过，等待执行" : "审批已驳回", "success");
          ctx.refresh();
        } catch (error) {
          toast(error.message, "error");
          setBusy(button, false);
        }
      };
      modal.querySelector("#approve-btn").addEventListener("click", (event) => decide("approve", event.currentTarget));
      modal.querySelector("#reject-btn").addEventListener("click", (event) => decide("reject", event.currentTarget));
    },
  });
  return root;
}

async function openExecuteConfirm(approval, ctx, button) {
  const ok = await confirmAction({
    title: "执行审批",
    message: `确认执行 ${approval.approval_no}？`,
    detail: `${approval.type_label} · ${approval.target_name || approval.target_id}。执行后将写入审计且不可重复执行。`,
    confirmText: "确认执行",
    danger: true,
  });
  if (!ok) return;
  setBusy(button, true, "执行中…");
  try {
    const result = await api.executeApproval(approval.id);
    toast(result.execution_result?.message || "审批已执行", "success", 4800);
    ctx.refresh();
  } catch (error) {
    toast(error.message, "error");
    setBusy(button, false);
  }
}

async function openApprovalDetail(approvalId, ctx) {
  const { root, close } = openDrawer({
    title: "审批详情",
    subtitle: "正在加载审批链路…",
    body: `<div class="skeleton sk-line" style="width:55%"></div><div class="skeleton sk-line" style="width:80%"></div><div class="skeleton sk-card" style="margin-top:14px"></div>`,
    footer: `<span></span>`,
  });
  let approval;
  try {
    approval = await api.approval(approvalId);
  } catch (error) {
    root.querySelector(".drawer-body").innerHTML = emptyState("alertCircle", "加载失败", error.message);
    return;
  }
  const head = root.querySelector(".drawer-head");
  head.querySelector("h3").textContent = `${approval.type_label} · ${approval.approval_no}`;
  head.querySelector("p").innerHTML = `${esc(approval.community_name || "")} · ${statusBadge(approval.status, "", "approval")} · ${esc(approval.risk_label || "高风险")}`;
  const payloadRows = Object.entries(approval.payload || {})
    .filter(([, value]) => value !== null && value !== undefined && value !== "")
    .map(([key, value]) => `<div class="context-kv"><span>${esc(key)}</span><b>${esc(typeof value === "object" ? JSON.stringify(value) : value)}</b></div>`)
    .join("");
  const timeline = (approval.timeline || [])
    .map(
      (item) => `<div class="timeline-item ${item.action.includes("failed") || item.action.includes("rejected") ? "fail" : ""}">
        <div class="t-title">${esc(actionLabel(item.action))}</div>
        <div class="t-time">${esc(fmtDateTime(item.at))} · ${esc(item.actor || "system")}</div>
        ${Object.keys(item.detail || {}).length ? `<div class="t-detail">${esc(Object.entries(item.detail).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`).join(" · "))}</div>` : ""}
      </div>`
    )
    .join("");
  root.querySelector(".drawer-body").innerHTML = `
    <div class="info-grid">
      <div class="info-item"><span>审批单号</span><b class="mono">${esc(approval.approval_no)}</b></div>
      <div class="info-item"><span>风险等级</span><b>${esc(approval.risk_label)}</b></div>
      <div class="info-item"><span>申请人</span><b>${esc(approval.requester?.display_name || "—")}</b></div>
      <div class="info-item"><span>审批人</span><b>${esc(approval.approver?.display_name || "待审批")}</b></div>
      <div class="info-item"><span>目标</span><b>${esc(approval.target_name || approval.target_id)}</b></div>
      <div class="info-item"><span>影响范围</span><b>${esc(approval.impact_scope || "—")}</b></div>
      <div class="info-item"><span>金额</span><b>${approval.amount ? `¥${fmtMoney(approval.amount)}` : "—"}</b></div>
      <div class="info-item"><span>发起来源</span><b>${esc(approval.source === "agent" ? "Agent 工作台" : "人工发起")}</b></div>
      <div class="info-item"><span>提交时间</span><b>${esc(fmtDateTime(approval.created_at))}</b></div>
      <div class="info-item"><span>决策时间</span><b>${esc(fmtDateTime(approval.decided_at))}</b></div>
      <div class="info-item"><span>执行时间</span><b>${esc(fmtDateTime(approval.executed_at))}</b></div>
      <div class="info-item"><span>trace_id</span><b class="mono" style="font-size:10px">${esc(approval.trace_id || "—")}</b></div>
    </div>
    <div class="section-label">业务理由</div>
    <div class="quote">${esc(approval.reason)}</div>
    ${approval.decision_comment ? `<div class="section-label">审批意见</div><div class="quote">${esc(approval.decision_comment)}</div>` : ""}
    <div class="section-label">执行参数</div>
    <div>${payloadRows || `<span class="muted" style="font-size:12px">无附加参数</span>`}</div>
    ${approval.execution_result ? `<div class="section-label">执行回执</div><div class="${approval.execution_result.result === "success" ? "quote" : "danger-box"}">${esc(approval.execution_result.message || JSON.stringify(approval.execution_result))}</div>` : ""}
    <div class="section-label">审批链路</div>
    ${timeline ? `<div class="timeline">${timeline}</div>` : `<div class="muted" style="font-size:12px">暂无流转记录。</div>`}`;

  const footer = root.querySelector(".drawer-foot");
  const buttons = [];
  if (canDecide() && approval.can_decide) buttons.push(`<button class="btn btn-ghost" data-foot="decide">审批决策</button>`);
  if (canDecide() && approval.can_execute) buttons.push(`<button class="btn btn-primary" data-foot="execute">执行审批</button>`);
  footer.innerHTML = buttons.join("") || `<span class="muted" style="font-size:11px">当前审批无可执行操作</span>`;
  footer.querySelectorAll("[data-foot]").forEach((button) => {
    button.addEventListener("click", () => {
      if (button.dataset.foot === "decide") openDecideModal(approval, ctx);
      else {
        openExecuteConfirm(approval, ctx, button);
      }
    });
  });
}

function actionLabel(action) {
  const map = {
    "approval.created": "审批申请创建",
    "approval.approved": "审批通过",
    "approval.rejected": "审批驳回",
    "approval.executed": "审批执行完成",
    "approval.execution_failed": "审批执行失败",
  };
  return map[action] || action;
}

/* 维修工单：列表、分派、处理、验收与关闭 */

import { api } from "../api.js";
import { store } from "../store.js";
import {
  icon, esc, fmtDateTime, fmtRelative, fmtNum, fmtMoney, statusBadge, priorityBadge, emptyState,
  openDrawer, openModal, confirmAction, toast, debounce, renderPagination, setBusy,
} from "../ui.js";

const ROLE = () => store.user.role;
const isOps = () => ["admin", "operator"].includes(ROLE());
const canHandle = () => ["admin", "operator", "technician"].includes(ROLE());
const canCreate = () => ["admin", "operator", "technician", "resident"].includes(ROLE());

const TABS = [
  { key: "", label: "全部" },
  { key: "pending", label: "待分派" },
  { key: "assigned", label: "已分派" },
  { key: "accepted", label: "已接单" },
  { key: "processing", label: "处理中" },
  { key: "pending_verification", label: "待验收" },
  { key: "closed", label: "已关闭" },
];

function actionButtons(ticket) {
  const buttons = [];
  if (canHandle() && ["pending", "assigned"].includes(ticket.status)) {
    buttons.push(`<button class="btn btn-soft btn-sm" data-ticket-action="accept" data-id="${ticket.id}">接单</button>`);
  }
  if (isOps() && ["pending", "assigned"].includes(ticket.status)) {
    buttons.push(`<button class="btn btn-ghost btn-sm" data-ticket-action="assign" data-id="${ticket.id}">分派</button>`);
  }
  if (canHandle() && ticket.status === "accepted") {
    buttons.push(`<button class="btn btn-soft btn-sm" data-ticket-action="start" data-id="${ticket.id}">开始</button>`);
  }
  if (canHandle() && ticket.status === "processing") {
    buttons.push(`<button class="btn btn-soft btn-sm" data-ticket-action="resolve" data-id="${ticket.id}">回填</button>`);
  }
  if (canHandle() && ["processing", "accepted", "pending_verification"].includes(ticket.status)) {
    buttons.push(`<button class="btn btn-soft btn-sm" data-ticket-action="verify" data-id="${ticket.id}">验收</button>`);
  }
  if (isOps() && ticket.status === "pending_verification" && ticket.heartbeat_checked && ticket.test_order_verified) {
    buttons.push(`<button class="btn btn-primary btn-sm" data-ticket-action="close" data-id="${ticket.id}">关闭</button>`);
  }
  buttons.push(`<button class="btn btn-ghost btn-sm" data-ticket-action="detail" data-id="${ticket.id}">详情</button>`);
  return buttons.join("");
}

export async function render(page, ctx) {
  const status = ctx.query.status || "";
  const priority = ctx.query.priority || "";
  const keyword = ctx.query.keyword || "";
  const pageNo = Math.max(1, Number(ctx.query.page) || 1);
  const communityId = store.state.currentCommunityId;

  const [list, dash] = await Promise.all([
    api.tickets({
      community_id: communityId || undefined,
      status: status || undefined,
      priority: priority || undefined,
      keyword: keyword || undefined,
      page: pageNo,
      page_size: 15,
    }),
    api.dashboard(7, communityId),
  ]);
  const byId = new Map(list.items.map((ticket) => [ticket.id, ticket]));

  const tabs = TABS.map(
    (tab) => `<button class="tab ${status === tab.key ? "active" : ""}" data-status="${tab.key}">${tab.label}</button>`
  ).join("");

  const rows = list.items
    .map(
      (ticket) => `<tr>
        <td>${priorityBadge(ticket.priority)}</td>
        <td><a href="#/tickets?id=${ticket.id}" class="strong" style="color:var(--ink)" data-detail="${ticket.id}">${esc(ticket.title)}</a><span class="subline"><span class="mono">${esc(ticket.ticket_no)}</span> · ${esc(ticket.source === "device" ? "设备自动" : ticket.source === "agent" ? "Agent 创建" : ticket.source === "complaint" ? "居民投诉" : "人工创建")}</span></td>
        <td>${esc(ticket.pile_code || "—")}<span class="subline">${esc(ticket.community_name || "")}</span></td>
        <td>${statusBadge(ticket.status)}</td>
        <td>${ticket.assignee ? esc(ticket.assignee.display_name) : `<span class="muted">未分派</span>`}</td>
        <td class="nowrap ${ticket.sla_overdue ? "" : "muted"}" style="${ticket.sla_overdue ? "color:#be123c;font-weight:600" : ""}">${ticket.sla_overdue ? "已超时" : "正常"}<span class="subline">${esc(fmtDateTime(ticket.sla_due_at))}</span></td>
        <td class="nowrap muted">${esc(ticket.age_text)}</td>
        <td><div class="table-actions">${actionButtons(ticket)}</div></td>
      </tr>`
    )
    .join("");

  page.innerHTML = `
    <div class="page-head">
      <div>
        <span class="eyebrow">运维协同</span>
        <h1>维修工单</h1>
        <p class="sub">${esc(store.communityName())} · 故障自动建单、分派、维修回填与测试订单验收</p>
      </div>
      <div class="page-actions">
        ${canCreate() ? `<button class="btn btn-primary btn-sm" id="new-ticket">${icon("plus", 14)} ${store.isResident ? "报修 / 投诉" : "创建工单"}</button>` : ""}
      </div>
    </div>
    <div class="mini-stats">
      <div class="mini-stat"><span>未闭环工单</span><b>${fmtNum(dash.summary.pending_tickets)} <small>张</small></b></div>
      <div class="mini-stat"><span>SLA 超时</span><b style="color:${dash.summary.overdue_tickets ? "#be123c" : "#087a54"}">${fmtNum(dash.summary.overdue_tickets)} <small>张</small></b></div>
      <div class="mini-stat"><span>故障设备</span><b>${fmtNum(dash.summary.fault_piles)} <small>台</small></b></div>
      <div class="mini-stat"><span>平均修复时长</span><b>${fmtNum(dash.summary.mttr_hours, 1)} <small>小时</small></b></div>
    </div>
    <div class="tabs">${tabs}</div>
    <div class="toolbar">
      <div class="input-icon">${icon("search", 16)}<input class="input" id="ticket-search" placeholder="搜索工单号、标题或设备…" value="${esc(keyword)}" /></div>
      <select class="select" id="priority-filter">
        <option value="">全部优先级</option>
        ${["P1", "P2", "P3"].map((p) => `<option value="${p}" ${priority === p ? "selected" : ""}>${p}</option>`).join("")}
      </select>
      <div class="toolbar-spacer"></div>
      <span class="muted" style="font-size:11px">共 ${list.total} 张工单</span>
    </div>
    <section class="card">
      <div class="table-wrap"><table class="data">
        <thead><tr><th>优先级</th><th>工单</th><th>设备 / 社区</th><th>状态</th><th>负责人</th><th>SLA</th><th>已持续</th><th style="text-align:right">操作</th></tr></thead>
        <tbody>${rows || `<tr><td colspan="8">${emptyState("ticket", "没有符合条件的工单", "设备故障会自动生成工单，也可以手动创建。", `<button class="btn btn-primary btn-sm" id="empty-new-ticket">${icon("plus", 14)} 创建工单</button>`)}</td></tr>`}</tbody>
      </table></div>
    </section>
    <div class="table-foot" id="ticket-pagination"></div>`;

  renderPagination(document.getElementById("ticket-pagination"), list, (nextPage) => {
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    if (priority) params.set("priority", priority);
    if (keyword) params.set("keyword", keyword);
    params.set("page", String(nextPage));
    location.hash = `#/tickets?${params}`;
  });

  document.querySelectorAll("[data-status]").forEach((tab) => {
    tab.addEventListener("click", () => {
      const params = new URLSearchParams();
      if (tab.dataset.status) params.set("status", tab.dataset.status);
      if (priority) params.set("priority", priority);
      if (keyword) params.set("keyword", keyword);
      location.hash = `#/tickets${params.size ? `?${params}` : ""}`;
    });
  });
  document.getElementById("priority-filter").addEventListener("change", (event) => {
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    if (event.target.value) params.set("priority", event.target.value);
    if (keyword) params.set("keyword", keyword);
    location.hash = `#/tickets${params.size ? `?${params}` : ""}`;
  });
  const search = document.getElementById("ticket-search");
  search.addEventListener(
    "input",
    debounce(() => {
      const params = new URLSearchParams();
      if (status) params.set("status", status);
      if (priority) params.set("priority", priority);
      if (search.value.trim()) params.set("keyword", search.value.trim());
      location.hash = `#/tickets${params.size ? `?${params}` : ""}`;
    }, 420)
  );
  const openNew = () => openNewTicketModal();
  document.getElementById("new-ticket")?.addEventListener("click", openNew);
  document.getElementById("empty-new-ticket")?.addEventListener("click", openNew);
  page.querySelectorAll("[data-detail]").forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      openTicketDetail(Number(link.dataset.detail), ctx);
    });
  });
  page.querySelectorAll("[data-ticket-action]").forEach((button) => {
    button.addEventListener("click", () => handleTicketAction(button, byId.get(Number(button.dataset.id)), ctx));
  });

  if (ctx.query.id) {
    openTicketDetail(Number(ctx.query.id), ctx);
  }
}

async function handleTicketAction(button, ticket, ctx, actionOverride = null) {
  if (!ticket) return;
  const action = actionOverride || button.dataset.ticketAction;
  if (action === "detail") return openTicketDetail(ticket.id, ctx);
  if (action === "assign") return openAssignModal(ticket, ctx);
  if (action === "verify") return openVerifyModal(ticket, ctx);
  if (action === "resolve") return openResolveModal(ticket, ctx);
  if (action === "close") {
    const ok = await confirmAction({
      title: "关闭工单",
      message: `确认关闭 ${ticket.ticket_no}？`,
      detail: "系统会再次校验设备心跳与测试订单，任一条件不满足将拒绝关闭。",
      confirmText: "关闭工单",
    });
    if (!ok) return;
    setBusy(button, true, "关闭中…");
    try {
      await api.closeTicket(ticket.id);
      toast("工单已关闭，审计已记录", "success");
      ctx.refresh();
    } catch (error) {
      toast(error.message, "error");
      setBusy(button, false);
    }
    return;
  }
  if (action === "accept" || action === "start") {
    setBusy(button, true, "处理中…");
    try {
      if (action === "accept") await api.acceptTicket(ticket.id);
      else await api.startTicket(ticket.id);
      toast(action === "accept" ? "已接单" : "已开始处理", "success");
      ctx.refresh();
    } catch (error) {
      toast(error.message, "error");
      setBusy(button, false);
    }
  }
}

function openAssignModal(ticket, ctx) {
  const { root } = openModal({
    title: "分派工单",
    subtitle: `${ticket.ticket_no} · ${ticket.title}`,
    body: `<div id="assignee-box"><div class="skeleton sk-line" style="width:70%"></div></div>`,
    footer: `<button class="btn btn-ghost" data-close>取消</button><button class="btn btn-primary" id="assign-submit" disabled>确认分派</button>`,
    onMount: async (modal, closeFn) => {
      const box = modal.querySelector("#assignee-box");
      const submit = modal.querySelector("#assign-submit");
      let selected = null;
      try {
        const data = await api.assignees(store.state.currentCommunityId || undefined);
        if (!data.items.length) {
          box.innerHTML = `<div class="warning-box">当前社区暂无维修或运营人员可分派。</div>`;
          return;
        }
        box.innerHTML = `<div class="stack" style="gap:7px">${data.items
          .map(
            (user) => `<button type="button" class="row-between" data-assignee="${user.id}" style="border:1px solid var(--line);background:var(--surface);border-radius:10px;padding:10px 12px;text-align:left">
              <div><b style="font-size:12.5px">${esc(user.display_name)}</b><div class="muted" style="font-size:10.5px">${esc(user.role_label)} · ${esc((user.communities || []).join("、"))}</div></div>
              <span class="badge badge-slate no-dot">${user.open_tickets} 张在处理</span>
            </button>`
          )
          .join("")}</div>`;
        box.querySelectorAll("[data-assignee]").forEach((row) => {
          row.addEventListener("click", () => {
            selected = Number(row.dataset.assignee);
            box.querySelectorAll("[data-assignee]").forEach((item) => {
              item.style.borderColor = item === row ? "var(--brand)" : "var(--line)";
              item.style.background = item === row ? "var(--brand-soft)" : "var(--surface)";
            });
            submit.disabled = false;
          });
        });
        submit.addEventListener("click", async () => {
          if (!selected) return;
          setBusy(submit, true, "分派中…");
          try {
            await api.assignTicket(ticket.id, selected);
            closeFn();
            toast("工单已分派", "success");
            ctx.refresh();
          } catch (error) {
            toast(error.message, "error");
            setBusy(submit, false);
          }
        });
      } catch (error) {
        box.innerHTML = `<div class="danger-box">${esc(error.message)}</div>`;
      }
    },
  });
  return root;
}

function openResolveModal(ticket, ctx) {
  const { root } = openModal({
    title: "维修回填",
    subtitle: `${ticket.ticket_no} · ${ticket.title}`,
    body: `<div class="field"><label for="resolution">处理结果</label><textarea class="textarea" id="resolution" placeholder="请填写维修过程、更换部件与当前状态，至少 5 个字。"></textarea><div class="hint">提交后工单进入「待验收」，需完成心跳检查与测试订单验证才能关闭。</div></div>`,
    footer: `<button class="btn btn-ghost" data-close>取消</button><button class="btn btn-primary" id="resolve-submit">提交回填</button>`,
    onMount: (modal, closeFn) => {
      const submit = modal.querySelector("#resolve-submit");
      submit.addEventListener("click", async () => {
        const resolution = modal.querySelector("#resolution").value.trim();
        if (resolution.length < 5) {
          toast("维修回填至少 5 个字", "warn");
          return;
        }
        setBusy(submit, true, "提交中…");
        try {
          await api.resolveTicket(ticket.id, resolution);
          closeFn();
          toast("维修回填已提交，进入待验收", "success");
          ctx.refresh();
        } catch (error) {
          toast(error.message, "error");
          setBusy(submit, false);
        }
      });
    },
  });
  setTimeout(() => root.querySelector("#resolution")?.focus(), 60);
}

function openVerifyModal(ticket, ctx) {
  const { root } = openModal({
    title: "提交测试订单验收",
    subtitle: `${ticket.ticket_no} · ${ticket.pile_code || ""}`,
    body: `<div class="warning-box">系统将校验设备最近心跳（60 分钟内）与测试订单状态。测试订单必须已完成，且属于同一台设备。</div>
      <div class="field" style="margin-top:14px"><label>选择已完成的测试订单</label><div id="test-order-box"><div class="skeleton sk-line" style="width:70%"></div></div></div>
      <div class="check-row" style="margin-top:14px">${icon(ticket.heartbeat_checked ? "checkCircle" : "clock", 15)} 心跳检查：${ticket.heartbeat_checked ? "已通过" : "尚未完成"}</div>
      <div class="check-row" style="margin-top:6px">${icon(ticket.test_order_verified ? "checkCircle" : "clock", 15)} 测试订单：${ticket.test_order_verified ? "已验证" : "待验证"}</div>`,
    footer: `<button class="btn btn-ghost" data-close>取消</button><button class="btn btn-primary" id="verify-submit" disabled>提交验收</button>`,
    onMount: async (modal, closeFn) => {
      const box = modal.querySelector("#test-order-box");
      const submit = modal.querySelector("#verify-submit");
      let selected = null;
      if (!ticket.pile_code) {
        box.innerHTML = `<div class="warning-box">工单未关联设备，请先补充设备信息。</div>`;
        return;
      }
      try {
        const data = await api.orders({ keyword: ticket.pile_code, status: "completed", page_size: 12 });
        if (!data.items.length) {
          box.innerHTML = `<div class="warning-box">该设备暂无已完成订单。请先在设备上完成一笔测试充电订单，再回来验收。</div>`;
          return;
        }
        box.innerHTML = `<select class="select" id="test-order-select"><option value="">请选择测试订单</option>${data.items
          .map((order) => `<option value="${order.id}">${esc(order.order_no)} · ${fmtNum(order.energy_kwh, 2)} kWh · ¥${fmtMoney(order.amount)} · ${esc(fmtDateTime(order.ended_at))}</option>`)
          .join("")}</select>`;
        box.querySelector("#test-order-select").addEventListener("change", (event) => {
          selected = Number(event.target.value) || null;
          submit.disabled = !selected;
        });
        submit.addEventListener("click", async () => {
          if (!selected) return;
          setBusy(submit, true, "验收中…");
          try {
            await api.verifyTicket(ticket.id, selected);
            closeFn();
            toast("心跳与测试订单均通过，工单待关闭", "success");
            ctx.refresh();
          } catch (error) {
            toast(error.message, "error");
            setBusy(submit, false);
          }
        });
      } catch (error) {
        box.innerHTML = `<div class="danger-box">${esc(error.message)}</div>`;
      }
    },
  });
  return root;
}

async function openTicketDetail(ticketId, ctx) {
  const { root, close } = openDrawer({
    title: "工单详情",
    subtitle: "正在加载工单时间线…",
    body: `<div class="skeleton sk-line" style="width:55%"></div><div class="skeleton sk-line" style="width:80%"></div><div class="skeleton sk-card" style="margin-top:14px"></div>`,
    footer: `<span></span>`,
  });
  let ticket;
  try {
    ticket = await api.ticket(ticketId);
  } catch (error) {
    root.querySelector(".drawer-body").innerHTML = emptyState("alertCircle", "加载失败", error.message);
    return;
  }
  const head = root.querySelector(".drawer-head");
  head.querySelector("h3").textContent = `${ticket.ticket_no} · ${ticket.title}`;
  head.querySelector("p").innerHTML = `${esc(ticket.community_name || "")} · ${esc(ticket.pile_code || "未关联设备")} · ${statusBadge(ticket.status)} ${priorityBadge(ticket.priority)}`;
  const timeline = (ticket.timeline || [])
    .map(
      (item) => `<div class="timeline-item">
        <div class="t-title">${esc(actionLabel(item.action))}</div>
        <div class="t-time">${esc(fmtDateTime(item.at))} · ${esc(item.actor || "system")}</div>
        ${Object.keys(item.detail || {}).length ? `<div class="t-detail">${esc(Object.entries(item.detail).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`).join(" · "))}</div>` : ""}
      </div>`
    )
    .join("");
  root.querySelector(".drawer-body").innerHTML = `
    <div class="info-grid">
      <div class="info-item"><span>状态</span><b>${statusBadge(ticket.status)}</b></div>
      <div class="info-item"><span>优先级 / SLA</span><b>${priorityBadge(ticket.priority)} · ${esc(fmtDateTime(ticket.sla_due_at))}</b></div>
      <div class="info-item"><span>社区</span><b>${esc(ticket.community_name || "—")}</b></div>
      <div class="info-item"><span>设备</span><b>${esc(ticket.pile_code || "—")} ${esc(ticket.pile_name || "")}</b></div>
      <div class="info-item"><span>创建人</span><b>${esc(ticket.reporter?.display_name || "系统 / 设备")}</b></div>
      <div class="info-item"><span>负责人</span><b>${esc(ticket.assignee?.display_name || "未分派")}</b></div>
      <div class="info-item"><span>创建时间</span><b>${esc(fmtDateTime(ticket.created_at))}</b></div>
      <div class="info-item"><span>已持续</span><b>${esc(ticket.age_text)}</b></div>
    </div>
    <div class="section-label">问题描述</div>
    <div class="quote">${esc(ticket.description || "—")}</div>
    ${ticket.resolution ? `<div class="section-label">维修回填</div><div class="quote">${esc(ticket.resolution)}</div>` : ""}
    <div class="section-label">验收检查</div>
    <div class="stack" style="gap:7px">
      <div class="check-row ${ticket.heartbeat_checked ? "ok" : "no"}">${icon(ticket.heartbeat_checked ? "checkCircle" : "clock", 15)} 设备心跳检查 ${ticket.heartbeat_checked ? "已通过" : "未完成"}</div>
      <div class="check-row ${ticket.test_order_verified ? "ok" : "no"}">${icon(ticket.test_order_verified ? "checkCircle" : "clock", 15)} 测试订单验证 ${ticket.test_order_verified ? "已通过" : "未完成"}</div>
      ${ticket.test_order_id ? `<div class="hint">测试订单 ID：${ticket.test_order_id}</div>` : ""}
    </div>
    <div class="section-label">状态时间线</div>
    ${timeline ? `<div class="timeline">${timeline}</div>` : `<div class="muted" style="font-size:12px">暂无流转记录。</div>`}`;

  const footer = root.querySelector(".drawer-foot");
  const buttons = [];
  if (canHandle() && ["pending", "assigned"].includes(ticket.status)) buttons.push(`<button class="btn btn-ghost" data-foot="accept">接单</button>`);
  if (isOps() && ["pending", "assigned", "accepted"].includes(ticket.status)) buttons.push(`<button class="btn btn-ghost" data-foot="assign">分派</button>`);
  if (canHandle() && ticket.status === "accepted") buttons.push(`<button class="btn btn-soft" data-foot="start">开始处理</button>`);
  if (canHandle() && ticket.status === "processing") buttons.push(`<button class="btn btn-soft" data-foot="resolve">维修回填</button>`);
  if (canHandle() && ["accepted", "processing", "pending_verification"].includes(ticket.status)) buttons.push(`<button class="btn btn-soft" data-foot="verify">提交验收</button>`);
  if (isOps() && ticket.status === "pending_verification" && ticket.heartbeat_checked && ticket.test_order_verified) buttons.push(`<button class="btn btn-primary" data-foot="close">关闭工单</button>`);
  footer.innerHTML = buttons.join("") || `<span class="muted" style="font-size:11px">当前状态无可执行操作</span>`;
  footer.querySelectorAll("[data-foot]").forEach((button) => {
    button.addEventListener("click", () => {
      const action = button.dataset.foot;
      if (action === "assign") openAssignModal(ticket, ctx);
      else if (action === "resolve") openResolveModal(ticket, ctx);
      else if (action === "verify") openVerifyModal(ticket, ctx);
      else if (action === "close") {
        confirmAction({
          title: "关闭工单",
          message: `确认关闭 ${ticket.ticket_no}？`,
          detail: "关闭前会再次校验设备心跳与测试订单，条件不满足将被拒绝。",
          confirmText: "关闭工单",
        }).then(async (ok) => {
          if (!ok) return;
          setBusy(button, true, "关闭中…");
          try {
            await api.closeTicket(ticket.id);
            toast("工单已关闭", "success");
            close();
            ctx.refresh();
          } catch (error) {
            toast(error.message, "error");
            setBusy(button, false);
          }
        });
      } else {
        handleTicketAction(button, ticket, ctx, action);
      }
    });
  });
}

function actionLabel(action) {
  const map = {
    "ticket.created": "工单创建",
    "ticket.assigned": "工单分派",
    "ticket.accepted": "维修接单",
    "ticket.started": "开始处理",
    "ticket.resolved": "维修回填",
    "ticket.verified": "测试订单验收",
    "ticket.closed": "工单关闭",
    "ticket.cancelled": "工单取消",
    "ticket.escalated": "故障升级",
  };
  return map[action] || action;
}

async function openNewTicketModal() {
  const communities = store.state.communities;
  const defaultCommunity = store.state.currentCommunityId || communities[0]?.id;
  let pileList = [];
  const { root } = openModal({
    title: store.isResident ? "提交报修 / 投诉" : "创建维修工单",
    subtitle: "关联设备可帮助维修人员快速定位问题",
    body: `<div class="form-grid">
        <div class="field"><label>社区</label><select class="select" id="ticket-community">${communities
          .map((c) => `<option value="${c.id}" ${c.id === defaultCommunity ? "selected" : ""}>${esc(c.name)}</option>`)
          .join("")}</select></div>
        <div class="field"><label>关联设备（可选）</label><select class="select" id="ticket-pile"><option value="">不关联具体设备</option></select></div>
        <div class="field span-2"><label>问题标题</label><input class="input" id="ticket-title" placeholder="例如：B 区 02 号桩充电中断，枪口无法拔出" /></div>
        <div class="field span-2"><label>问题描述</label><textarea class="textarea" id="ticket-desc" placeholder="请描述现象、发生时间和影响范围。"></textarea></div>
        ${!store.isResident ? `<div class="field span-2"><label>优先级</label><div class="segmented" id="ticket-priority"><button type="button" data-p="P3" class="active">P3</button><button type="button" data-p="P2">P2</button><button type="button" data-p="P1">P1</button></div></div>` : ""}
      </div>`,
    footer: `<button class="btn btn-ghost" data-close>取消</button><button class="btn btn-primary" id="create-ticket-submit">提交</button>`,
    onMount: async (modal, closeFn) => {
      const communitySelect = modal.querySelector("#ticket-community");
      const pileSelect = modal.querySelector("#ticket-pile");
      let priority = "P3";
      modal.querySelectorAll("[data-p]").forEach((button) => {
        button.addEventListener("click", () => {
          priority = button.dataset.p;
          modal.querySelectorAll("[data-p]").forEach((item) => item.classList.toggle("active", item === button));
        });
      });
      const loadPiles = async () => {
        pileSelect.innerHTML = `<option value="">加载中…</option>`;
        try {
          const data = await api.piles({ community_id: Number(communitySelect.value), page_size: 100 });
          pileList = data.items;
          pileSelect.innerHTML = `<option value="">不关联具体设备</option>${data.items
            .map((pile) => `<option value="${pile.id}">${esc(pile.code)} · ${esc(pile.name)}（${esc(pile.status)}）</option>`)
            .join("")}`;
        } catch {
          pileSelect.innerHTML = `<option value="">设备加载失败</option>`;
        }
      };
      communitySelect.addEventListener("change", loadPiles);
      await loadPiles();
      const submit = modal.querySelector("#create-ticket-submit");
      submit.addEventListener("click", async () => {
        const title = modal.querySelector("#ticket-title").value.trim();
        const description = modal.querySelector("#ticket-desc").value.trim();
        if (title.length < 4) {
          toast("标题至少 4 个字", "warn");
          return;
        }
        setBusy(submit, true, "提交中…");
        try {
          const ticket = await api.createTicket({
            community_id: Number(communitySelect.value),
            pile_id: pileSelect.value ? Number(pileSelect.value) : undefined,
            title,
            description,
            priority,
          });
          closeFn();
          toast(`工单 ${ticket.ticket_no} 已创建`, "success");
          location.hash = `#/tickets?id=${ticket.id}`;
        } catch (error) {
          toast(error.message, "error");
          setBusy(submit, false);
        }
      });
    },
  });
  return root;
}

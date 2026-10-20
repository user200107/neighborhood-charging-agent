/* 充电设备：列表、详情、事件、停机审批与报修 */

import { api } from "../api.js";
import { store } from "../store.js";
import {
  icon, esc, fmtDateTime, fmtRelative, fmtNum, fmtMoney, statusBadge, priorityBadge,
  emptyState, openDrawer, openModal, toast, debounce, renderPagination, setBusy, pill,
} from "../ui.js";

const STATUS_TABS = [
  { key: "", label: "全部" },
  { key: "online", label: "在线" },
  { key: "fault", label: "故障" },
  { key: "offline", label: "离线" },
  { key: "maintenance", label: "维护" },
];

const EVENT_LABELS = {
  heartbeat: "心跳上报",
  power: "功率上报",
  current: "电流上报",
  temperature: "温度告警",
  offline: "设备离线",
  online: "设备上线",
  interrupted: "充电中断",
  fault: "故障告警",
  recovered: "故障恢复",
};

function eventSummary(event) {
  const payload = event.payload || {};
  const bits = [];
  if (payload.temperature_c !== undefined) bits.push(`温度 ${payload.temperature_c}℃`);
  if (payload.power_kw !== undefined) bits.push(`功率 ${payload.power_kw}kW`);
  if (payload.current_a !== undefined) bits.push(`电流 ${payload.current_a}A`);
  if (payload.fault_code) bits.push(`故障码 ${payload.fault_code}`);
  if (payload.message) bits.push(payload.message);
  if (payload.online !== undefined) bits.push(payload.online ? "在线" : "离线");
  return bits.join(" · ") || "—";
}

export async function render(page, ctx) {
  const status = ctx.query.status || "";
  const keyword = ctx.query.keyword || "";
  const pageNo = Math.max(1, Number(ctx.query.page) || 1);
  const communityId = store.state.currentCommunityId;

  const [list, dash] = await Promise.all([
    api.piles({ community_id: communityId || undefined, status: status || undefined, keyword: keyword || undefined, page: pageNo, page_size: 12 }),
    api.dashboard(1, communityId),
  ]);

  const statusCounts = Object.fromEntries((dash.pile_status || []).map((item) => [item.key, item.value]));
  const total = dash.summary.total_piles;
  const online = dash.summary.online_piles;
  const faults = dash.summary.fault_piles;
  const offline = dash.summary.offline_piles;
  const maintenance = dash.summary.maintenance_piles;

  const tabs = STATUS_TABS.map(
    (tab) => `<button class="tab ${status === tab.key ? "active" : ""}" data-status="${tab.key}">
      ${tab.label}<span class="count">${tab.key === "" ? total : tab.key === "online" ? online : statusCounts[tab.key] || 0}</span>
    </button>`
  ).join("");

  const cards = list.items
    .map(
      (pile) => `<article class="device-card s-${esc(pile.status)}" data-pile="${pile.id}">
        <div class="device-top">
          <div style="min-width:0">
            <div class="device-code">${esc(pile.code)}</div>
            <div class="device-name">${esc(pile.name)}</div>
            <div class="device-meta">${esc(pile.community_name)} · ${esc(pile.zone_name)}</div>
          </div>
          ${statusBadge(pile.status)}
        </div>
        <div class="device-stats">
          <div class="device-stat"><span>额定功率</span><b>${fmtNum(pile.rated_power_kw)} kW</b></div>
          <div class="device-stat ${pile.temperature_c >= 65 ? "warn" : ""}"><span>温度</span><b>${fmtNum(pile.temperature_c, 1)} ℃</b></div>
          <div class="device-stat"><span>心跳</span><b style="font-size:11px">${esc(fmtRelative(pile.last_heartbeat_at))}</b></div>
        </div>
        <div class="connector-row">
          ${(pile.connectors || []).map((connector) => pill(connector.status, `${connector.code} · ${connector.status === "idle" ? "空闲" : connector.status === "charging" ? "充电中" : connector.status === "reserved" ? "已预约" : connector.status === "fault" ? "故障" : "离线"}`)).join("")}
        </div>
        <div class="device-foot">
          <div class="price">${pile.connectors?.length ? `¥${fmtMoney(pile.connectors[0].price_per_kwh)}<span class="muted" style="font-size:10px">/度起</span>` : "—"}</div>
          <button class="btn btn-ghost btn-sm" data-open="${pile.id}">查看详情 ${icon("arrowRight", 13)}</button>
        </div>
      </article>`
    )
    .join("");

  page.innerHTML = `
    <div class="page-head">
      <div>
        <span class="eyebrow">资产运营</span>
        <h1>充电设备</h1>
        <p class="sub">${esc(store.communityName())} · 设备状态、枪口占用与故障事件</p>
      </div>
      <div class="page-actions">
        <button class="btn btn-ghost btn-sm" id="device-refresh">${icon("refresh", 14)} 刷新</button>
        ${store.can("agent") ? `<a class="btn btn-primary btn-sm" href="#/agent?prompt=${encodeURIComponent("当前有哪些设备故障？")}">${icon("agent", 14)} 故障归因</a>` : ""}
      </div>
    </div>
    <div class="mini-stats">
      <div class="mini-stat"><span>设备总数</span><b>${fmtNum(total)} <small>台</small></b></div>
      <div class="mini-stat"><span>在线可用</span><b style="color:#087a54">${fmtNum(online)} <small>台</small></b></div>
      <div class="mini-stat"><span>故障设备</span><b style="color:#be123c">${fmtNum(faults)} <small>台</small></b></div>
      <div class="mini-stat"><span>离线 / 维护</span><b>${fmtNum(offline)} / ${fmtNum(maintenance)} <small>台</small></b></div>
    </div>
    <div class="tabs">${tabs}</div>
    <div class="toolbar">
      <div class="input-icon">${icon("search", 16)}<input class="input" id="device-search" placeholder="搜索设备编号或名称…" value="${esc(keyword)}" /></div>
      <div class="toolbar-spacer"></div>
      <span class="muted" style="font-size:11px">共 ${list.total} 台设备 · 按社区与编号排序</span>
    </div>
    ${cards ? `<div class="device-grid">${cards}</div>` : `<div class="card">${emptyState("device", "没有符合条件的设备", "试试切换状态或清空搜索关键词。")}</div>`}
    <div class="table-foot" id="device-pagination"></div>`;

  renderPagination(document.getElementById("device-pagination"), list, (nextPage) => {
    const params = new URLSearchParams({ ...(status ? { status } : {}), ...(keyword ? { keyword } : {}), page: String(nextPage) });
    location.hash = `#/devices?${params}`;
  });

  document.getElementById("device-refresh").addEventListener("click", () => ctx.refresh());
  document.querySelectorAll("[data-status]").forEach((tab) => {
    tab.addEventListener("click", () => {
      const params = new URLSearchParams();
      if (tab.dataset.status) params.set("status", tab.dataset.status);
      if (keyword) params.set("keyword", keyword);
      location.hash = `#/devices${params.size ? `?${params}` : ""}`;
    });
  });
  const search = document.getElementById("device-search");
  search.addEventListener(
    "input",
    debounce(() => {
      const params = new URLSearchParams();
      if (status) params.set("status", status);
      if (search.value.trim()) params.set("keyword", search.value.trim());
      location.hash = `#/devices${params.size ? `?${params}` : ""}`;
    }, 420)
  );
  const open = (id) => openPileDetail(Number(id));
  document.querySelectorAll("[data-pile]").forEach((card) => {
    card.addEventListener("click", (event) => {
      if (event.target.closest("button")) return;
      open(card.dataset.pile);
    });
  });
  document.querySelectorAll("[data-open]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      open(button.dataset.open);
    });
  });
}

async function openPileDetail(pileId) {
  const { root, close } = openDrawer({
    title: "设备详情",
    subtitle: "正在加载设备档案…",
    body: `<div class="skeleton sk-line" style="width:60%"></div><div class="skeleton sk-line" style="width:90%"></div><div class="skeleton sk-card" style="margin-top:14px"></div>`,
    footer: `<span></span>`,
  });
  let pile;
  try {
    pile = await api.pile(pileId);
  } catch (error) {
    root.querySelector(".drawer-body").innerHTML = emptyState("alertCircle", "加载失败", error.message);
    return;
  }

  const events = (pile.events || [])
    .map(
      (event) => `<div class="timeline-item ${event.severity === "critical" ? "fail" : ""}">
        <div class="t-title">${esc(EVENT_LABELS[event.event_type] || event.event_type)} ${event.severity !== "info" ? `<span class="badge ${event.severity === "critical" ? "badge-red" : "badge-amber"}" style="margin-left:5px">${esc(event.severity)}</span>` : ""}</div>
        <div class="t-time">${esc(fmtDateTime(event.occurred_at))} · ${esc(event.event_no)}</div>
        <div class="t-detail">${esc(eventSummary(event))}</div>
      </div>`
    )
    .join("");
  const tickets = (pile.tickets || [])
    .map(
      (ticket) => `<div class="row-between" style="padding:9px 0;border-bottom:1px dashed var(--line)">
        <div class="row" style="gap:8px;min-width:0">${priorityBadge(ticket.priority)}<div style="min-width:0"><b style="font-size:11.5px" class="nowrap">${esc(ticket.title)}</b><div class="muted" style="font-size:10px">${esc(ticket.ticket_no)} · ${esc(ticket.status)}</div></div></div>
        ${statusBadge(ticket.status)}
      </div>`
    )
    .join("");
  const orders = (pile.recent_orders || [])
    .map(
      (order) => `<div class="row-between" style="padding:8px 0;border-bottom:1px dashed var(--line)">
        <div><span class="mono" style="font-size:10.5px">${esc(order.order_no)}</span><div class="muted" style="font-size:10px">${esc(order.user_name || "")} · ${esc(fmtDateTime(order.created_at))}</div></div>
        <div style="text-align:right"><div style="font-size:11.5px;font-weight:600">¥${fmtMoney(order.amount)}</div>${statusBadge(order.status)}</div>
      </div>`
    )
    .join("");

  const head = root.querySelector(".drawer-head");
  head.querySelector("h3").textContent = `${pile.code} · ${pile.name}`;
  head.querySelector("p").innerHTML = `${esc(pile.community_name)} · ${esc(pile.zone_name)} · ${statusBadge(pile.status)}`;

  const canStop = ["admin", "operator"].includes(store.user.role) && pile.status !== "maintenance";
  const canTicket = ["admin", "operator", "technician", "resident"].includes(store.user.role);
  const footer = root.querySelector(".drawer-foot");
  if (footer) {
    footer.innerHTML = `
      <a class="btn btn-ghost" href="#/agent?prompt=${encodeURIComponent(`诊断 ${pile.code} 的故障`)}">${icon("agent", 15)} 让 Agent 诊断</a>
      ${canTicket ? `<button class="btn btn-ghost" id="device-ticket">${icon("ticket", 15)} ${store.isResident ? "报修 / 投诉" : "创建工单"}</button>` : ""}
      ${canStop ? `<button class="btn btn-primary" id="device-stop">${icon("stop", 15)} 申请停机</button>` : ""}`;
    footer.querySelector("#device-ticket")?.addEventListener("click", () => openTicketModal(pile));
    footer.querySelector("#device-stop")?.addEventListener("click", () => openStopModal(pile));
  }

  root.querySelector(".drawer-body").innerHTML = `
    <div class="info-grid">
      <div class="info-item"><span>所属社区</span><b>${esc(pile.community_name)}</b></div>
      <div class="info-item"><span>区域</span><b>${esc(pile.zone_name)}</b></div>
      <div class="info-item"><span>设备型号</span><b>${esc(pile.model)} · ${esc(pile.vendor)}</b></div>
      <div class="info-item"><span>额定功率</span><b>${fmtNum(pile.rated_power_kw)} kW</b></div>
      <div class="info-item"><span>实时温度</span><b style="color:${pile.temperature_c >= 65 ? "#be123c" : "inherit"}">${fmtNum(pile.temperature_c, 1)} ℃</b></div>
      <div class="info-item"><span>当前功率</span><b>${fmtNum(pile.current_power_kw, 1)} kW</b></div>
      <div class="info-item"><span>最近心跳</span><b>${esc(fmtRelative(pile.last_heartbeat_at))}</b></div>
      <div class="info-item"><span>信号 / 固件</span><b>${pile.signal_strength}/5 · ${esc(pile.firmware)}</b></div>
      <div class="info-item"><span>安装时间</span><b>${esc(fmtDateTime(pile.installed_at))}</b></div>
      <div class="info-item"><span>设备 ID</span><b class="mono">#${pile.id}</b></div>
    </div>
    <div class="section-label">枪口状态</div>
    <div class="table-wrap"><table class="data">
      <thead><tr><th>枪口</th><th>类型</th><th>状态</th><th class="num">功率</th><th class="num">电费 + 服务费</th><th class="num">累计电量</th></tr></thead>
      <tbody>${(pile.connectors || [])
        .map(
          (connector) => `<tr><td class="strong">${esc(connector.code)} 号</td><td>${esc(connector.gun_type)}</td><td>${statusBadge(connector.status)}</td><td class="num">${fmtNum(connector.power_kw)} kW</td><td class="num">¥${fmtMoney(connector.price_per_kwh)} + ${fmtMoney(connector.service_fee)}</td><td class="num">${fmtNum(connector.total_energy_kwh, 1)} kWh</td></tr>`
        )
        .join("")}</tbody>
    </table></div>
    <div class="section-label">最近事件</div>
    ${events ? `<div class="timeline">${events}</div>` : `<div class="muted" style="font-size:12px">暂无设备事件。</div>`}
    <div class="section-label">关联工单</div>
    ${tickets || `<div class="muted" style="font-size:12px">该设备暂无工单。</div>`}
    <div class="section-label">最近订单</div>
    ${orders || `<div class="muted" style="font-size:12px">该设备暂无订单。</div>`}`;
}

function openStopModal(pile) {
  const { root, close } = openModal({
    title: "申请设备停机",
    subtitle: `${pile.code} · ${pile.name}`,
    body: `<div class="warning-box">${icon("alert", 14)} 停机属于高风险动作。提交后会进入审批中心，由财务/管理员决策通过后才能执行，Agent 与运营人员均不能直接停机。</div>
      <div class="field" style="margin-top:14px"><label for="stop-reason">业务理由</label>
        <textarea class="textarea" id="stop-reason" placeholder="例如：充电模块温度持续超过 75℃，申请临时停机检修。"></textarea>
        <div class="hint">需说明影响范围与安全风险，至少 4 个字。</div>
      </div>
      <div class="info-grid" style="margin-top:14px">
        <div class="info-item"><span>影响枪口</span><b>${pile.connector_count} 个</b></div>
        <div class="info-item"><span>当前状态</span><b>${statusBadge(pile.status)}</b></div>
      </div>`,
    footer: `<button class="btn btn-ghost" data-close>取消</button><button class="btn btn-primary" id="stop-submit">提交审批</button>`,
    onMount: (modal, closeFn) => {
      const submit = modal.querySelector("#stop-submit");
      submit.addEventListener("click", async () => {
        const reason = modal.querySelector("#stop-reason").value.trim();
        if (reason.length < 4) {
          toast("请填写至少 4 个字的业务理由", "warn");
          return;
        }
        setBusy(submit, true, "提交中…");
        try {
          const approval = await api.createApproval({
            type: "stop_pile",
            target_id: String(pile.id),
            reason,
            payload: { pile_id: pile.id, action: "maintenance" },
          });
          closeFn();
          toast(`审批 ${approval.approval_no} 已创建，等待审批`, "success", 4200);
          location.hash = "#/approvals";
        } catch (error) {
          toast(error.message, "error");
          setBusy(submit, false);
        }
      });
    },
  });
  setTimeout(() => root.querySelector("#stop-reason")?.focus(), 60);
}

function openTicketModal(pile) {
  const { root, close } = openModal({
    title: store.isResident ? "提交报修 / 投诉" : "创建设备工单",
    subtitle: `${pile.code} · ${pile.name}`,
    body: `<div class="field"><label for="ticket-title">问题标题</label><input class="input" id="ticket-title" placeholder="例如：枪口锁止异常，用户无法拔枪" /></div>
      <div class="field" style="margin-top:12px"><label for="ticket-desc">问题描述</label><textarea class="textarea" id="ticket-desc" placeholder="请描述现象、发生时间与影响范围。"></textarea></div>
      ${!store.isResident ? `<div class="field" style="margin-top:12px"><label>优先级</label><div class="segmented" id="ticket-priority"><button type="button" data-p="P3" class="active">P3</button><button type="button" data-p="P2">P2</button><button type="button" data-p="P1">P1</button></div></div>` : `<div class="hint" style="margin-top:10px">居民报修默认按 P3 处理，运营人员会核实后升级优先级。</div>`}`,
    footer: `<button class="btn btn-ghost" data-close>取消</button><button class="btn btn-primary" id="ticket-submit">创建工单</button>`,
    onMount: (modal, closeFn) => {
      let priority = "P3";
      modal.querySelectorAll("[data-p]").forEach((button) => {
        button.addEventListener("click", () => {
          priority = button.dataset.p;
          modal.querySelectorAll("[data-p]").forEach((item) => item.classList.toggle("active", item === button));
        });
      });
      const submit = modal.querySelector("#ticket-submit");
      submit.addEventListener("click", async () => {
        const title = modal.querySelector("#ticket-title").value.trim();
        const description = modal.querySelector("#ticket-desc").value.trim();
        if (title.length < 4) {
          toast("标题至少 4 个字", "warn");
          return;
        }
        setBusy(submit, true, "创建中…");
        try {
          const ticket = await api.createTicket({ pile_id: pile.id, title, description, priority });
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
  setTimeout(() => root.querySelector("#ticket-title")?.focus(), 60);
}

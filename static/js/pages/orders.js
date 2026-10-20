/* 订单与预约 */

import { api } from "../api.js";
import { store } from "../store.js";
import {
  icon, esc, fmtDateTime, fmtMoney, fmtNum, fmtDuration, statusBadge, emptyState, openDrawer,
  openModal, confirmAction, toast, debounce, renderPagination, setBusy, downloadBlob, avatar,
} from "../ui.js";

const TABS = [
  { key: "", label: "全部" },
  { key: "charging", label: "充电中" },
  { key: "reserved", label: "已预约" },
  { key: "completed", label: "已完成" },
  { key: "pending_payment", label: "待支付" },
  { key: "abnormal", label: "异常" },
  { key: "cancelled", label: "已取消" },
];

function localInputValue(date) {
  const pad = (value) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function orderActions(order) {
  const buttons = [];
  if (order.status === "reserved") buttons.push(`<button class="btn btn-soft btn-sm" data-action="start" data-id="${order.id}">${icon("play", 13)} 开始</button>`);
  if (order.status === "charging") buttons.push(`<button class="btn btn-soft btn-sm" data-action="complete" data-id="${order.id}">${icon("stop", 13)} 结束</button>`);
  if (["pending_payment", "reserved"].includes(order.status)) buttons.push(`<button class="btn btn-ghost btn-sm" data-action="cancel" data-id="${order.id}">取消</button>`);
  return buttons.join("");
}

export async function render(page, ctx) {
  const status = ctx.query.status || "";
  const keyword = ctx.query.keyword || "";
  const pageNo = Math.max(1, Number(ctx.query.page) || 1);
  const communityId = store.state.currentCommunityId;

  const list = await api.orders({
    community_id: communityId || undefined,
    status: status || undefined,
    keyword: keyword || undefined,
    page: pageNo,
    page_size: 15,
  });
  const byId = new Map(list.items.map((order) => [order.id, order]));

  const tabs = TABS.map(
    (tab) => `<button class="tab ${status === tab.key ? "active" : ""}" data-status="${tab.key}">${tab.label}</button>`
  ).join("");

  const rows = list.items
    .map(
      (order) => `<tr>
        <td><span class="mono" style="font-size:11px">${esc(order.order_no)}</span><span class="subline">${esc(order.community_name || "")}</span></td>
        <td>${store.isStaff ? `${esc(order.user_name || "—")}<span class="subline">充电用户</span>` : esc(order.pile_name || "—")}</td>
        <td>${esc(order.pile_code || "—")} / ${esc(order.connector_code || "—")}${store.isStaff ? `<span class="subline">${esc(order.pile_name || "")}</span>` : ""}</td>
        <td>${statusBadge(order.status)}</td>
        <td class="num">${order.energy_kwh ? `${fmtNum(order.energy_kwh, 2)} kWh` : "—"}</td>
        <td class="num strong">¥${fmtMoney(order.amount)}${order.refund_amount ? `<span class="subline" style="color:#be123c">退 ¥${fmtMoney(order.refund_amount)}</span>` : ""}</td>
        <td class="nowrap muted">${esc(fmtDateTime(order.created_at))}<span class="subline">${esc(order.duration_text)}</span></td>
        <td><div class="table-actions">${orderActions(order)}<button class="btn btn-ghost btn-sm" data-action="detail" data-id="${order.id}">详情</button></div></td>
      </tr>`
    )
    .join("");

  page.innerHTML = `
    <div class="page-head">
      <div>
        <span class="eyebrow">交易履约</span>
        <h1>订单与预约</h1>
        <p class="sub">${esc(store.communityName())} · 充电订单、预约时段与状态流转</p>
      </div>
      <div class="page-actions">
        ${store.isStaff ? `<button class="btn btn-ghost btn-sm" id="export-orders">${icon("download", 14)} 导出 CSV</button>` : ""}
        <button class="btn btn-primary btn-sm" id="new-order">${icon("plus", 14)} 新建充电</button>
      </div>
    </div>
    <div class="tabs">${tabs}</div>
    <div class="toolbar">
      <div class="input-icon">${icon("search", 16)}<input class="input" id="order-search" placeholder="搜索订单号、设备或用户…" value="${esc(keyword)}" /></div>
      <div class="toolbar-spacer"></div>
      <span class="muted" style="font-size:11px">共 ${list.total} 笔订单</span>
    </div>
    <section class="card">
      <div class="table-wrap"><table class="data">
        <thead><tr><th>订单</th><th>${store.isStaff ? "用户" : "设备"}</th><th>充电位置</th><th>状态</th><th style="text-align:right">电量</th><th style="text-align:right">金额</th><th>时间</th><th style="text-align:right">操作</th></tr></thead>
        <tbody>${rows || `<tr><td colspan="8">${emptyState("order", "没有符合条件的订单", "可以新建一笔充电订单，或切换筛选条件。", `<button class="btn btn-primary btn-sm" id="empty-new-order">${icon("plus", 14)} 新建充电</button>`)}</td></tr>`}</tbody>
      </table></div>
    </section>
    <div class="table-foot" id="order-pagination"></div>`;

  renderPagination(document.getElementById("order-pagination"), list, (nextPage) => {
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    if (keyword) params.set("keyword", keyword);
    params.set("page", String(nextPage));
    location.hash = `#/orders?${params}`;
  });

  document.querySelectorAll("[data-status]").forEach((tab) => {
    tab.addEventListener("click", () => {
      const params = new URLSearchParams();
      if (tab.dataset.status) params.set("status", tab.dataset.status);
      if (keyword) params.set("keyword", keyword);
      location.hash = `#/orders${params.size ? `?${params}` : ""}`;
    });
  });
  const search = document.getElementById("order-search");
  search.addEventListener(
    "input",
    debounce(() => {
      const params = new URLSearchParams();
      if (status) params.set("status", status);
      if (search.value.trim()) params.set("keyword", search.value.trim());
      location.hash = `#/orders${params.size ? `?${params}` : ""}`;
    }, 420)
  );

  const openNew = () => openNewOrderModal(ctx);
  document.getElementById("new-order").addEventListener("click", openNew);
  document.getElementById("empty-new-order")?.addEventListener("click", openNew);
  document.getElementById("export-orders")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    setBusy(button, true, "导出中…");
    try {
      const params = new URLSearchParams({ days: "30" });
      if (communityId) params.set("community_id", String(communityId));
      const { blob, filename } = await api.download(`/api/reports/orders.csv?${params}`);
      downloadBlob(blob, filename);
      toast("订单 CSV 已导出", "success");
    } catch (error) {
      toast(error.message, "error");
    } finally {
      setBusy(button, false);
    }
  });

  const handleAction = async (button) => {
    const order = byId.get(Number(button.dataset.id));
    if (!order) return;
    if (button.dataset.action === "detail") {
      openOrderDetail(order.id);
    } else if (button.dataset.action === "start") {
      const ok = await confirmAction({
        title: "开始充电",
        message: `确认开始订单 ${order.order_no} 的充电？`,
        detail: `${order.pile_code} · ${order.connector_code} 号枪口`,
        confirmText: "开始充电",
      });
      if (!ok) return;
      setBusy(button, true, "启动中…");
      try {
        await api.startOrder(order.id);
        toast("充电已开始", "success");
        ctx.refresh();
      } catch (error) {
        toast(error.message, "error");
        setBusy(button, false);
      }
    } else if (button.dataset.action === "complete") {
      const ok = await confirmAction({
        title: "结束充电",
        message: `确认结束订单 ${order.order_no}？系统将按实际时长模拟计费。`,
        detail: `当前电量 ${fmtNum(order.energy_kwh, 2)} kWh，预估金额 ¥${fmtMoney(order.amount)}`,
        confirmText: "结束并结算",
      });
      if (!ok) return;
      setBusy(button, true, "结算中…");
      try {
        await api.completeOrder(order.id, {});
        toast("订单已完成结算", "success");
        ctx.refresh();
      } catch (error) {
        toast(error.message, "error");
        setBusy(button, false);
      }
    } else if (button.dataset.action === "cancel") {
      openCancelModal(order, ctx);
    }
  };
  page.querySelectorAll("[data-action]").forEach((button) => {
    button.addEventListener("click", () => handleAction(button));
  });
}

function openCancelModal(order, ctx) {
  const { root } = openModal({
    title: "取消订单",
    subtitle: `${order.order_no} · ${order.pile_code || ""}`,
    body: `<div class="field"><label for="cancel-reason">取消原因</label><textarea class="textarea" id="cancel-reason" placeholder="请说明取消原因">用户临时取消</textarea></div>`,
    footer: `<button class="btn btn-ghost" data-close>保留订单</button><button class="btn btn-danger" id="cancel-submit">确认取消</button>`,
    onMount: (modal, closeFn) => {
      const submit = modal.querySelector("#cancel-submit");
      submit.addEventListener("click", async () => {
        const reason = modal.querySelector("#cancel-reason").value.trim() || "用户取消";
        setBusy(submit, true, "取消中…");
        try {
          await api.cancelOrder(order.id, reason);
          closeFn();
          toast("订单已取消", "success");
          ctx.refresh();
        } catch (error) {
          toast(error.message, "error");
          setBusy(submit, false);
        }
      });
    },
  });
  setTimeout(() => root.querySelector("#cancel-reason")?.focus(), 60);
}

async function openOrderDetail(orderId) {
  const { root } = openDrawer({
    title: "订单详情",
    subtitle: "正在加载订单与状态时间线…",
    body: `<div class="skeleton sk-line" style="width:50%"></div><div class="skeleton sk-line" style="width:80%"></div><div class="skeleton sk-card" style="margin-top:14px"></div>`,
  });
  let order;
  try {
    order = await api.order(orderId);
  } catch (error) {
    root.querySelector(".drawer-body").innerHTML = emptyState("alertCircle", "加载失败", error.message);
    return;
  }
  const head = root.querySelector(".drawer-head");
  head.querySelector("h3").textContent = order.order_no;
  head.querySelector("p").innerHTML = `${esc(order.community_name || "")} · ${esc(order.pile_code || "")} / ${esc(order.connector_code || "")} · ${statusBadge(order.status)}`;
  const timeline = (order.timeline || [])
    .map(
      (item) => `<div class="timeline-item ${item.action.includes("cancel") ? "fail" : ""}">
        <div class="t-title">${esc(actionLabel(item.action))}</div>
        <div class="t-time">${esc(fmtDateTime(item.at))} · ${esc(item.actor || "system")}</div>
        ${Object.keys(item.detail || {}).length ? `<div class="t-detail">${esc(Object.entries(item.detail).map(([key, value]) => `${key}: ${value}`).join(" · "))}</div>` : ""}
      </div>`
    )
    .join("");
  root.querySelector(".drawer-body").innerHTML = `
    <div class="info-grid">
      <div class="info-item"><span>用户</span><b>${esc(order.user_name || "—")}</b></div>
      <div class="info-item"><span>社区</span><b>${esc(order.community_name || "—")}</b></div>
      <div class="info-item"><span>设备</span><b>${esc(order.pile_code || "—")} · ${esc(order.pile_name || "")}</b></div>
      <div class="info-item"><span>枪口</span><b>${esc(order.connector_code || "—")} 号</b></div>
      <div class="info-item"><span>开始时间</span><b>${esc(fmtDateTime(order.starts_at))}</b></div>
      <div class="info-item"><span>结束时间</span><b>${esc(fmtDateTime(order.ended_at))}</b></div>
      <div class="info-item"><span>充电时长</span><b>${esc(order.duration_text)}</b></div>
      <div class="info-item"><span>电量</span><b>${fmtNum(order.energy_kwh, 2)} kWh</b></div>
      <div class="info-item"><span>电费单价</span><b>¥${fmtMoney(order.unit_price)} / 度</b></div>
      <div class="info-item"><span>服务费</span><b>¥${fmtMoney(order.service_fee)} / 度</b></div>
      <div class="info-item"><span>支付方式</span><b>${esc(order.payment_method)}</b></div>
      <div class="info-item"><span>来源</span><b>${esc(order.source)}</b></div>
    </div>
    <div class="section-label">结算</div>
    <div class="card card-pad" style="background:var(--surface-2);box-shadow:none">
      <div class="row-between"><span class="muted">订单金额</span><b style="font-size:20px">¥${fmtMoney(order.amount)}</b></div>
      ${order.refund_amount ? `<div class="row-between" style="margin-top:6px"><span class="muted">已退款</span><b style="color:#be123c">¥${fmtMoney(order.refund_amount)}</b></div>` : ""}
      ${order.cancel_reason ? `<div class="hint" style="margin-top:8px">取消原因：${esc(order.cancel_reason)}</div>` : ""}
    </div>
    <div class="section-label">状态时间线</div>
    ${timeline ? `<div class="timeline">${timeline}</div>` : `<div class="muted" style="font-size:12px">暂无状态变更记录。</div>`}`;
}

function actionLabel(action) {
  const map = {
    "order.created": "订单创建",
    "order.started": "开始充电",
    "order.completed": "充电完成",
    "order.cancelled": "订单取消",
  };
  return map[action] || action;
}

async function openNewOrderModal(ctx) {
  const communities = store.state.communities;
  const defaultCommunity = store.state.currentCommunityId || communities[0]?.id;
  const now = new Date();
  const start = new Date(now.getTime() + 60 * 60 * 1000);
  const end = new Date(start.getTime() + 2 * 60 * 60 * 1000);
  let mode = "now";
  let selectedConnector = null;
  const { root } = openModal({
    title: "新建充电",
    subtitle: "查询可用枪口，立即开始或预约时段",
    size: "modal-lg",
    body: `<div class="form-grid">
        <div class="field"><label>社区</label><select class="select" id="new-community">${communities
          .map((c) => `<option value="${c.id}" ${c.id === defaultCommunity ? "selected" : ""}>${esc(c.name)}</option>`)
          .join("")}</select></div>
        <div class="field"><label>模式</label><div class="segmented" id="new-mode"><button type="button" data-mode="now" class="active">立即充电</button><button type="button" data-mode="reserved">预约时段</button></div></div>
        <div class="field span-2" id="reserved-fields" hidden>
          <div class="form-grid">
            <div class="field"><label>开始时间</label><input class="input" type="datetime-local" id="new-start" value="${localInputValue(start)}" /></div>
            <div class="field"><label>结束时间</label><input class="input" type="datetime-local" id="new-end" value="${localInputValue(end)}" /></div>
          </div>
        </div>
      </div>
      <div class="row-between" style="margin:16px 0 8px"><span class="section-label" style="margin:0">选择枪口</span><button class="btn btn-ghost btn-sm" id="reload-availability">${icon("refresh", 13)} 重新查询</button></div>
      <div id="availability-box"><div class="skeleton sk-card"></div></div>`,
    footer: `<button class="btn btn-ghost" data-close>取消</button><button class="btn btn-primary" id="create-order-submit" disabled>确认下单</button>`,
    onMount: (modal, closeFn) => {
      const box = modal.querySelector("#availability-box");
      const submit = modal.querySelector("#create-order-submit");
      const reservedFields = modal.querySelector("#reserved-fields");
      const communitySelect = modal.querySelector("#new-community");
      const startInput = modal.querySelector("#new-start");
      const endInput = modal.querySelector("#new-end");

      const load = async () => {
        selectedConnector = null;
        submit.disabled = true;
        box.innerHTML = `<div class="skeleton sk-card"></div>`;
        const communityId = Number(communitySelect.value);
        const startsAt = mode === "reserved" ? new Date(startInput.value) : new Date();
        const endsAt = mode === "reserved" ? new Date(endInput.value) : new Date(Date.now() + 30 * 60 * 1000);
        if (Number.isNaN(startsAt.getTime()) || Number.isNaN(endsAt.getTime()) || endsAt <= startsAt) {
          box.innerHTML = `<div class="warning-box">预约结束时间必须晚于开始时间。</div>`;
          return;
        }
        try {
          const data = await api.availability({
            community_id: communityId,
            starts_at: startsAt.toISOString(),
            ends_at: endsAt.toISOString(),
            limit: 12,
          });
          if (!data.items.length) {
            box.innerHTML = emptyState("device", "该时段没有可用枪口", "请调整社区、时间，或取消部分预约后重试。");
            return;
          }
          box.innerHTML = `<div class="grid grid-2" style="gap:9px">${data.items
            .map(
              (item, index) => `<button type="button" class="device-card" data-connector="${item.id}" style="text-align:left;padding:12px;border-radius:12px;box-shadow:none">
                <div class="row-between"><div><div class="device-code">${esc(item.pile.code)} / ${esc(item.code)}</div><div class="device-name" style="font-size:12.5px">${esc(item.pile.name)}</div><div class="device-meta">${esc(item.pile.community_name)} · ${esc(item.gun_type)}</div></div><span class="badge badge-green">空闲</span></div>
                <div class="row-between" style="margin-top:9px"><span class="muted" style="font-size:10.5px">${fmtNum(item.power_kw)} kW</span><b style="font-size:12px">¥${fmtMoney(item.price_per_kwh)} <span class="muted" style="font-weight:400;font-size:10px">+服务费 ${fmtMoney(item.service_fee)}</span></b></div>
              </button>`
            )
            .join("")}</div>`;
          box.querySelectorAll("[data-connector]").forEach((card) => {
            card.addEventListener("click", () => {
              selectedConnector = Number(card.dataset.connector);
              box.querySelectorAll("[data-connector]").forEach((item) => {
                item.style.borderColor = item === card ? "var(--brand)" : "var(--line)";
                item.style.background = item === card ? "var(--brand-soft)" : "var(--surface)";
              });
              submit.disabled = false;
            });
          });
        } catch (error) {
          box.innerHTML = `<div class="danger-box">${esc(error.message)}</div>`;
        }
      };

      modal.querySelectorAll("[data-mode]").forEach((button) => {
        button.addEventListener("click", () => {
          mode = button.dataset.mode;
          modal.querySelectorAll("[data-mode]").forEach((item) => item.classList.toggle("active", item === button));
          reservedFields.hidden = mode !== "reserved";
          load();
        });
      });
      communitySelect.addEventListener("change", load);
      modal.querySelector("#reload-availability").addEventListener("click", load);
      startInput.addEventListener("change", load);
      endInput.addEventListener("change", load);

      submit.addEventListener("click", async () => {
        if (!selectedConnector) {
          toast("请选择一个可用枪口", "warn");
          return;
        }
        const payload = { connector_id: selectedConnector, mode, payment_method: "wechat" };
        if (mode === "reserved") {
          payload.starts_at = new Date(startInput.value).toISOString();
          payload.ends_at = new Date(endInput.value).toISOString();
        }
        setBusy(submit, true, "创建中…");
        try {
          const order = await api.createOrder(payload);
          closeFn();
          toast(`订单 ${order.order_no} 已创建`, "success");
          ctx.refresh();
        } catch (error) {
          toast(error.message, "error");
          setBusy(submit, false);
        }
      });
      load();
    },
  });
  return root;
}

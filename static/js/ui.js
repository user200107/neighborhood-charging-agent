/* UI 基础工具：图标、格式化、状态标签、Toast、Modal、Drawer */

const ICONS = {
  dashboard: '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
  device: '<path d="M7 3h10v4a5 5 0 0 1-10 0V3Z"/><path d="M12 12v9"/><path d="M8 21h8"/><path d="M7 7H4a1 1 0 0 0-1 1v2a3 3 0 0 0 3 3h1"/><path d="M17 7h3a1 1 0 0 1 1 1v2a3 3 0 0 1-3 3h-1"/>',
  order: '<path d="M6 2h12v20l-3-2-3 2-3-2-3 2V2Z"/><path d="M9 7h6"/><path d="M9 11h6"/><path d="M9 15h3"/>',
  ticket: '<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18v3h3l6.3-6.3a4 4 0 0 0 5.4-5.4l-2.1 2.1-2.9-2.9 2-2.2Z"/>',
  approval: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="m9 12 2 2 4-4"/>',
  agent: '<path d="M12 3 13.6 8.4 19 10l-5.4 1.6L12 17l-1.6-5.4L5 10l5.4-1.6L12 3Z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8L19 15Z"/><path d="M5 16l.6 1.6L7 18l-1.4.4L5 20l-.6-1.6L3 18l1.4-.4L5 16Z"/>',
  report: '<path d="M3 3v18h18"/><path d="M7 15v3"/><path d="M12 9v9"/><path d="M17 5v13"/>',
  audit: '<path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v5h5"/><path d="M12 7v5l3 2"/>',
  logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  refresh: '<path d="M21 12a9 9 0 1 1-2.6-6.4"/><path d="M21 3v6h-6"/>',
  plus: '<path d="M12 5v14"/><path d="M5 12h14"/>',
  chevron: '<path d="m6 9 6 6 6-6"/>',
  chevronRight: '<path d="m9 18 6-6-6-6"/>',
  x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  send: '<path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/>',
  bolt: '<path d="M13 2 3 14h9l-1 8 10-12h-9l1-8Z"/>',
  alert: '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
  alertCircle: '<circle cx="12" cy="12" r="10"/><path d="M12 8v4"/><path d="M12 16h.01"/>',
  check: '<path d="m20 6-11 11-5-5"/>',
  checkCircle: '<circle cx="12" cy="12" r="10"/><path d="m8 12 3 3 5-6"/>',
  clock: '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
  user: '<path d="M20 21a8 8 0 1 0-16 0"/><circle cx="12" cy="8" r="4"/>',
  users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
  filter: '<path d="M22 3H2l8 9.5V19l4 2v-8.5L22 3Z"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/><path d="M12 15V3"/>',
  menu: '<path d="M4 6h16"/><path d="M4 12h16"/><path d="M4 18h16"/>',
  pin: '<path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z"/><circle cx="12" cy="10" r="3"/>',
  activity: '<path d="M3 12h4l3-9 4 18 3-9h4"/>',
  trend: '<path d="m3 17 6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
  battery: '<rect x="2" y="7" width="17" height="10" rx="2"/><path d="M22 11v2"/><path d="M6 11v2"/>',
  thermometer: '<path d="M14 14.8V4a2 2 0 0 0-4 0v10.8a4 4 0 1 0 4 0Z"/>',
  wifi: '<path d="M5 12.5a10 10 0 0 1 14 0"/><path d="M8.5 16a5 5 0 0 1 7 0"/><path d="M12 20h.01"/><path d="M2 9a15 15 0 0 1 20 0"/>',
  wifiOff: '<path d="m2 2 20 20"/><path d="M8.5 16a5 5 0 0 1 7 0"/><path d="M5 12.5a10 10 0 0 1 5-2.7"/><path d="M2 9a15 15 0 0 1 7-4"/><path d="M12 20h.01"/>',
  calendar: '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4"/><path d="M8 2v4"/><path d="M3 10h18"/>',
  arrowRight: '<path d="M5 12h14"/><path d="m13 6 6 6-6 6"/>',
  external: '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><path d="M15 3h6v6"/><path d="M10 14 21 3"/>',
  more: '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
  play: '<circle cx="12" cy="12" r="10"/><path d="m10 8 6 4-6 4V8Z"/>',
  stop: '<circle cx="12" cy="12" r="10"/><rect x="9" y="9" width="6" height="6" rx="1"/>',
  ban: '<circle cx="12" cy="12" r="10"/><path d="m4.9 4.9 14.2 14.2"/>',
  edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
  info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
  lock: '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
  database: '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 1.7 4 3 9 3s9-1.3 9-3V5"/><path d="M3 12c0 1.7 4 3 9 3s9-1.3 9-3"/>',
  cpu: '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4"/><path d="M15 2v4"/><path d="M9 18v4"/><path d="M15 18v4"/><path d="M2 9h4"/><path d="M2 15h4"/><path d="M18 9h4"/><path d="M18 15h4"/>',
  gauge: '<path d="M12 14 8 9"/><path d="M3.5 18a9 9 0 1 1 17 0"/><circle cx="12" cy="14" r="1.5"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/>',
  file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6"/><path d="M8 13h8"/><path d="M8 17h5"/>',
  key: '<circle cx="7.5" cy="15.5" r="4.5"/><path d="m10.5 12.5 9-9"/><path d="m17 6 2 2"/><path d="m14 9 2 2"/>',
  eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
  eyeOff: '<path d="m2 2 20 20"/><path d="M6.7 6.7A10.5 10.5 0 0 0 2 12s3.5 7 10 7a10 10 0 0 0 4.3-1"/><path d="M9.9 5.2A10 10 0 0 1 12 5c6.5 0 10 7 10 7a16 16 0 0 1-2.4 3.2"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/>',
  spark: '<path d="m12 3 1.9 5.6L19 10l-5.1 1.4L12 17l-1.9-5.6L5 10l5.1-1.4L12 3Z"/>',
  chart: '<path d="M3 3v18h18"/><rect x="7" y="12" width="3" height="6"/><rect x="12" y="8" width="3" height="10"/><rect x="17" y="5" width="3" height="13"/>',
  arrowUp: '<path d="m18 15-6-6-6 6"/>',
  arrowDown: '<path d="m6 9 6 6 6-6"/>',
  copy: '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  trash: '<path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
  terminal: '<path d="m4 17 6-6-6-6"/><path d="M12 19h8"/>',
};

export function icon(name, size = 16, cls = "") {
  const path = ICONS[name] || ICONS.info;
  return `<svg class="${cls}" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`;
}

export function esc(value) {
  if (value === null || value === undefined) return "";
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function fmtMoney(value, digits = 2) {
  const num = Number(value || 0);
  return num.toLocaleString("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function fmtNum(value, digits = 0) {
  return Number(value || 0).toLocaleString("zh-CN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function fmtPct(value, digits = 1) {
  return `${Number(value || 0).toFixed(digits)}%`;
}

const TZ = "Asia/Shanghai";

export function fmtDateTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: TZ, month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
  }).format(date);
}

export function fmtDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("zh-CN", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" }).format(date);
}

export function fmtTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("zh-CN", { timeZone: TZ, hour: "2-digit", minute: "2-digit", hour12: false }).format(date);
}

export function fmtRelative(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  const diff = Date.now() - date.getTime();
  const abs = Math.abs(diff);
  const future = diff < 0;
  const prefix = future ? "后" : "前";
  if (abs < 60_000) return future ? "即将" : "刚刚";
  if (abs < 3_600_000) return `${Math.floor(abs / 60_000)} 分钟${prefix}`;
  if (abs < 86_400_000) return `${Math.floor(abs / 3_600_000)} 小时${prefix}`;
  if (abs < 30 * 86_400_000) return `${Math.floor(abs / 86_400_000)} 天${prefix}`;
  return fmtDate(value);
}

export function fmtDuration(seconds) {
  if (seconds === null || seconds === undefined || seconds < 0) return "—";
  const s = Math.floor(seconds);
  if (s < 60) return `${s} 秒`;
  if (s < 3600) return `${Math.floor(s / 60)} 分钟`;
  if (s < 86400) return `${Math.floor(s / 3600)} 小时 ${Math.floor((s % 3600) / 60)} 分`;
  return `${Math.floor(s / 86400)} 天 ${Math.floor((s % 86400) / 3600)} 小时`;
}

export function todayLabel() {
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: TZ, year: "numeric", month: "long", day: "numeric", weekday: "long",
  }).format(new Date());
}

export function greeting() {
  const hour = Number(new Intl.DateTimeFormat("en-US", { timeZone: TZ, hour: "2-digit", hour12: false }).format(new Date()));
  if (hour < 6) return "夜深了";
  if (hour < 11) return "早上好";
  if (hour < 14) return "中午好";
  if (hour < 18) return "下午好";
  return "晚上好";
}

const STATUS_MAP = {
  // pile
  online: ["在线", "green"], offline: ["离线", "gray"], fault: ["故障", "red"], maintenance: ["维护", "amber"],
  // connector
  idle: ["空闲", "green"], charging: ["充电中", "teal"], reserved: ["已预约", "violet"],
  // order
  pending_payment: ["待支付", "amber"], completed: ["已完成", "green"], cancelled: ["已取消", "gray"], abnormal: ["异常", "red"],
  // ticket
  pending: ["待分派", "amber"], assigned: ["已分派", "blue"], accepted: ["已接单", "violet"],
  processing: ["处理中", "teal"], pending_verification: ["待验收", "amber"], closed: ["已关闭", "green"],
  // approval
  approved: ["已通过", "blue"], rejected: ["已驳回", "red"], executing: ["执行中", "violet"], executed: ["已执行", "green"], failed: ["执行失败", "red"],
  // misc
  active: ["生效中", "green"], inactive: ["已停用", "gray"], success: ["成功", "green"],
};

export function statusMeta(status) {
  const [label, color] = STATUS_MAP[status] || [status || "未知", "slate"];
  return { label, color };
}

export function statusBadge(status, extra = "", context = "") {
  let meta = statusMeta(status);
  if (context === "approval" && status === "pending") meta = { label: "待审批", color: "amber" };
  if (context === "order" && status === "pending") meta = { label: "待支付", color: "amber" };
  return `<span class="badge badge-${meta.color} ${extra}">${esc(meta.label)}</span>`;
}

export function pill(status, text) {
  const label = text || statusMeta(status).label;
  return `<span class="connector-pill c-${esc(status)}">${esc(label)}</span>`;
}

export function priorityBadge(priority) {
  return `<span class="priority ${esc(priority)}">${esc(priority)}</span>`;
}

export function roleLabel(role) {
  return { admin: "系统管理员", operator: "运营人员", technician: "维修人员", finance: "财务/审批", resident: "居民用户" }[role] || role;
}

export function initials(name) {
  const text = String(name || "?").trim();
  if (!text) return "?";
  return text.length <= 2 ? text : text.slice(-2);
}

export function avatar(name, role) {
  return `<span class="avatar role-${esc(role || "")}">${esc(initials(name))}</span>`;
}

export function emptyState(iconName, title, desc, actionHtml = "") {
  return `<div class="empty">
    <div class="e-ico">${icon(iconName, 24)}</div>
    <b>${esc(title)}</b>
    ${desc ? `<p>${esc(desc)}</p>` : ""}
    ${actionHtml}
  </div>`;
}

export function skeletonPage() {
  return `<div class="stack">
    <div class="skeleton sk-card" style="height:150px"></div>
    <div class="grid grid-3">
      <div class="skeleton sk-card"></div>
      <div class="skeleton sk-card"></div>
      <div class="skeleton sk-card"></div>
    </div>
  </div>`;
}

export function skeletonRows(count = 6) {
  return `<div style="padding:8px 0">${Array.from({ length: count })
    .map(() => `<div class="skeleton sk-line" style="width:${76 + Math.random() * 22}%"></div>`)
    .join("")}</div>`;
}

export function debounce(fn, wait = 280) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), wait);
  };
}

export function toast(message, type = "info", duration = 3800) {
  const root = document.getElementById("toast-root");
  if (!root) return;
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  const ic = type === "success" ? "checkCircle" : type === "error" ? "alertCircle" : type === "warn" ? "alert" : "info";
  el.innerHTML = `${icon(ic, 16)}<div>${esc(message)}</div><button class="toast-close" aria-label="关闭">${icon("x", 13)}</button>`;
  root.appendChild(el);
  const remove = () => {
    el.style.opacity = "0";
    el.style.transform = "translateY(6px)";
    setTimeout(() => el.remove(), 180);
  };
  el.querySelector(".toast-close").addEventListener("click", remove);
  setTimeout(remove, duration);
}

let overlaySeq = 0;
const openOverlays = new Map();

function buildOverlay(inner, { onClose, className = "overlay" } = {}) {
  const root = document.getElementById("modal-root");
  const id = `ov-${++overlaySeq}`;
  const overlay = document.createElement("div");
  overlay.className = className;
  overlay.id = id;
  overlay.innerHTML = inner;
  root.appendChild(overlay);
  document.body.style.overflow = "hidden";
  const onKey = (event) => {
    if (event.key === "Escape") close();
  };
  const close = () => {
    if (!overlay.isConnected) return;
    overlay.remove();
    document.removeEventListener("keydown", onKey);
    openOverlays.delete(id);
    if (!root.children.length) document.body.style.overflow = "";
    onClose?.();
  };
  openOverlays.set(id, close);
  overlay.addEventListener("mousedown", (event) => {
    if (event.target === overlay) close();
  });
  document.addEventListener("keydown", onKey);
  overlay.querySelectorAll("[data-close]").forEach((btn) => btn.addEventListener("click", close));
  return { overlay, close, id };
}

export function closeAllOverlays() {
  [...openOverlays.values()].reverse().forEach((close) => close());
  document.body.style.overflow = "";
}

export function openModal({ title, subtitle = "", body = "", footer = "", size = "", onMount, onClose } = {}) {
  const { overlay, close } = buildOverlay(
    `<div class="modal ${size}" role="dialog" aria-modal="true">
      <div class="modal-head">
        <div>
          <h3>${esc(title)}</h3>
          ${subtitle ? `<p>${esc(subtitle)}</p>` : ""}
        </div>
        <button class="modal-close" data-close aria-label="关闭">${icon("x", 16)}</button>
      </div>
      <div class="modal-body">${body}</div>
      ${footer ? `<div class="modal-foot">${footer}</div>` : ""}
    </div>`,
    { onClose }
  );
  const dialog = overlay.querySelector(".modal");
  onMount?.(dialog, close);
  return { root: dialog, close };
}

export function openDrawer({ title, subtitle = "", body = "", footer = "", onMount, onClose } = {}) {
  const { overlay, close } = buildOverlay(
    `<div class="drawer" role="dialog" aria-modal="true">
      <div class="drawer-head">
        <div>
          <h3 style="font-size:18px;letter-spacing:-.02em">${esc(title)}</h3>
          ${subtitle ? `<p class="muted" style="font-size:12px;margin-top:3px">${esc(subtitle)}</p>` : ""}
        </div>
        <button class="modal-close" data-close aria-label="关闭">${icon("x", 16)}</button>
      </div>
      <div class="drawer-body">${body}</div>
      ${footer ? `<div class="drawer-foot">${footer}</div>` : ""}
    </div>`,
    { className: "drawer-overlay", onClose }
  );
  const drawer = overlay.querySelector(".drawer");
  onMount?.(drawer, close);
  return { root: drawer, close };
}

export function confirmAction({
  title = "确认操作",
  message = "",
  detail = "",
  confirmText = "确认",
  cancelText = "取消",
  danger = false,
} = {}) {
  return new Promise((resolve) => {
    let settled = false;
    const { close } = openModal({
      title,
      body: `<p style="font-size:13px;color:var(--ink-2);line-height:1.75">${esc(message)}</p>
        ${detail ? `<div class="${danger ? "danger-box" : "warning-box"}" style="margin-top:14px">${esc(detail)}</div>` : ""}`,
      footer: `<button class="btn btn-ghost" data-cancel>${esc(cancelText)}</button>
        <button class="btn ${danger ? "btn-danger" : "btn-primary"}" data-confirm>${esc(confirmText)}</button>`,
      onClose: () => {
        if (!settled) {
          settled = true;
          resolve(false);
        }
      },
      onMount: (root, closeFn) => {
        root.querySelector("[data-cancel]").addEventListener("click", () => {
          settled = true;
          resolve(false);
          closeFn();
        });
        root.querySelector("[data-confirm]").addEventListener("click", () => {
          settled = true;
          resolve(true);
          closeFn();
        });
      },
    });
    return close;
  });
}

export function renderPagination(container, { page, pages, total, pageSize }, onChange) {
  if (!container) return;
  const safePages = Math.max(1, Number(pages) || 1);
  const current = Math.min(Math.max(1, Number(page) || 1), safePages);
  const start = Math.max(1, current - 2);
  const end = Math.min(safePages, current + 2);
  let buttons = `<button data-page="${current - 1}" ${current <= 1 ? "disabled" : ""}>‹</button>`;
  if (start > 1) buttons += `<button data-page="1">1</button>${start > 2 ? `<span class="muted" style="padding:0 3px">…</span>` : ""}`;
  for (let p = start; p <= end; p++) buttons += `<button data-page="${p}" class="${p === current ? "active" : ""}">${p}</button>`;
  if (end < safePages) buttons += `${end < safePages - 1 ? `<span class="muted" style="padding:0 3px">…</span>` : ""}<button data-page="${safePages}">${safePages}</button>`;
  buttons += `<button data-page="${current + 1}" ${current >= safePages ? "disabled" : ""}>›</button>`;
  container.innerHTML = `<span class="muted" style="font-size:11px">共 ${fmtNum(total)} 条 · 第 ${current}/${safePages} 页</span><div class="pagination">${buttons}</div>`;
  container.querySelectorAll("[data-page]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = Number(btn.dataset.page);
      if (target >= 1 && target <= safePages && target !== current) onChange(target);
    });
  });
}

export function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1500);
}

export function setBusy(button, busy, text = "处理中…") {
  if (!button) return;
  if (busy) {
    button.dataset.original = button.innerHTML;
    button.disabled = true;
    button.innerHTML = `<span class="typing" aria-hidden="true"><span></span><span></span><span></span></span>${esc(text)}`;
  } else {
    button.disabled = false;
    if (button.dataset.original) button.innerHTML = button.dataset.original;
  }
}

export function safeArray(data) {
  if (Array.isArray(data)) return data;
  if (data && Array.isArray(data.items)) return data.items;
  return [];
}

export function qs(root, selector) {
  return root.querySelector(selector);
}

export function qsa(root, selector) {
  return Array.from(root.querySelectorAll(selector));
}

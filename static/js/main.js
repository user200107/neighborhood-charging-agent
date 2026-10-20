/* 应用入口：登录、外壳、路由 */

import { api, tokens } from "./api.js";
import { store } from "./store.js";
import {
  icon, esc, toast, avatar, roleLabel, openModal, greeting, todayLabel, emptyState, closeAllOverlays,
} from "./ui.js";

import * as dashboard from "./pages/dashboard.js";
import * as devices from "./pages/devices.js";
import * as orders from "./pages/orders.js";
import * as tickets from "./pages/tickets.js";
import * as approvals from "./pages/approvals.js";
import * as agent from "./pages/agent.js";
import * as reports from "./pages/reports.js";
import * as audit from "./pages/audit.js";

const PAGES = { dashboard, devices, orders, tickets, approvals, agent, reports, audit };

const PAGE_META = {
  dashboard: { title: "运营总览", crumb: "工作台", icon: "dashboard" },
  devices: { title: "充电设备", crumb: "资产运营", icon: "device" },
  orders: { title: "订单与预约", crumb: "交易履约", icon: "order" },
  tickets: { title: "维修工单", crumb: "运维协同", icon: "ticket" },
  approvals: { title: "审批中心", crumb: "风险控制", icon: "approval" },
  agent: { title: "Agent 工作台", crumb: "智能运营", icon: "agent" },
  reports: { title: "运营报表", crumb: "数据分析", icon: "report" },
  audit: { title: "审计日志", crumb: "安全合规", icon: "audit" },
};

const NAV_GROUPS = [
  { label: "运营", items: ["dashboard", "devices", "orders", "tickets", "approvals"] },
  { label: "智能", items: ["agent"] },
  { label: "分析", items: ["reports", "audit"] },
];

const app = document.getElementById("app");
let renderSeq = 0;

function parseHash() {
  const raw = (location.hash || "").replace(/^#\/?/, "");
  const [name, qs] = raw.split("?");
  const query = {};
  new URLSearchParams(qs || "").forEach((value, key) => {
    query[key] = value;
  });
  return { name: name || "dashboard", query };
}

function defaultRoute() {
  const allowed = store.state.menus;
  if (allowed.includes("dashboard")) return "dashboard";
  return allowed[0] || "orders";
}

export function navigate(path) {
  const target = path.startsWith("#") ? path : `#/${path.replace(/^\/+/, "")}`;
  if (location.hash === target) {
    renderRoute();
  } else {
    location.hash = target;
  }
}

function navHtml() {
  return NAV_GROUPS.map((group) => {
    const links = group.items
      .filter((key) => store.can(key))
      .map(
        (key) => `<a class="nav-item" data-nav="${key}" href="#/${key}">
          ${icon(PAGE_META[key].icon, 18)}
          <span>${PAGE_META[key].title}</span>
          ${key === "approvals" ? `<span class="nav-badge" data-approval-badge hidden>0</span>` : ""}
          ${key === "agent" ? `<span class="nav-badge" style="background:rgba(124,92,252,.18);color:#c4b5fd">AI</span>` : ""}
        </a>`
      )
      .join("");
    return links ? `<div class="sidebar-section">${group.label}</div><nav class="nav">${links}</nav>` : "";
  }).join("");
}

function renderShell() {
  const user = store.user;
  const options = [
    `<option value="">全部社区</option>`,
    ...store.state.communities.map(
      (community) =>
        `<option value="${community.id}" ${store.state.currentCommunityId === community.id ? "selected" : ""}>${esc(community.name)}</option>`
    ),
  ].join("");
  app.innerHTML = `
    <div class="shell">
      <aside class="sidebar" id="sidebar">
        <a class="sidebar-brand" href="#/${defaultRoute()}">
          <span class="logo-mark" aria-hidden="true"></span>
          <span><b>邻里充电</b><span>NEIGHBOR ENERGY</span></span>
        </a>
        ${navHtml()}
        <div class="sidebar-spacer"></div>
        <div class="sidebar-card">
          <div class="sc-title">${icon("shield", 14)} 安全运营边界</div>
          <p>Agent 只读查询直接执行；停机、退款、调价、批量改派必须转人工审批。</p>
          <div class="sc-bar"><span style="width:100%"></span></div>
        </div>
        <div class="sidebar-user">
          ${avatar(user.display_name, user.role)}
          <div style="min-width:0">
            <b>${esc(user.display_name)}</b>
            <span>${esc(roleLabel(user.role))}</span>
          </div>
          <button class="icon-btn-dark" id="sidebar-logout" title="退出登录" aria-label="退出登录">${icon("logout", 15)}</button>
        </div>
      </aside>
      <div class="sidebar-scrim" id="sidebar-scrim"></div>
      <div class="main">
        <header class="topbar">
          <button class="icon-btn menu-btn" id="menu-toggle" aria-label="打开菜单">${icon("menu", 18)}</button>
          <div class="topbar-left">
            <div class="topbar-crumb">
              <span>邻里充电</span><span class="sep">/</span><span id="crumb-current">${PAGE_META[defaultRoute()].crumb}</span>
            </div>
            <div class="topbar-title" id="topbar-title">${PAGE_META[defaultRoute()].title}</div>
          </div>
          <div class="topbar-spacer"></div>
          <div class="topbar-actions">
            <div class="community-select">
              ${icon("pin", 15)}
              <select class="select" id="community-select" aria-label="切换社区">${options}</select>
            </div>
            <button class="icon-btn hide-sm" id="refresh-btn" title="刷新当前页面" aria-label="刷新">${icon("refresh", 17)}</button>
            <button class="icon-btn" id="bell-btn" title="待办与审批" aria-label="待办与审批">${icon("alert", 17)}<span class="dot" id="bell-dot" hidden></span></button>
            <button class="user-chip" id="user-chip" aria-label="账号菜单">
              ${avatar(user.display_name, user.role)}
              <div class="user-meta"><b>${esc(user.display_name)}</b><span>${esc(roleLabel(user.role))}</span></div>
              <span class="chev">${icon("chevron", 15)}</span>
            </button>
          </div>
        </header>
        <main class="page" id="page"></main>
      </div>
    </div>`;

  document.getElementById("menu-toggle").addEventListener("click", () => {
    document.getElementById("sidebar").classList.add("open");
    document.getElementById("sidebar-scrim").classList.add("show");
    store.toggleSidebar(true);
  });
  const closeSidebar = () => {
    document.getElementById("sidebar").classList.remove("open");
    document.getElementById("sidebar-scrim").classList.remove("show");
    store.toggleSidebar(false);
  };
  document.getElementById("sidebar-scrim").addEventListener("click", closeSidebar);
  document.querySelectorAll("[data-nav]").forEach((link) => link.addEventListener("click", closeSidebar));
  document.getElementById("community-select").addEventListener("change", (event) => {
    store.setCommunity(event.target.value || null);
    toast(`数据范围已切换为「${store.communityName()}」`, "info", 2200);
  });
  document.getElementById("refresh-btn").addEventListener("click", () => {
    renderRoute(true);
    toast("已刷新", "success", 1600);
  });
  document.getElementById("bell-btn").addEventListener("click", () => {
    if (store.can("approvals")) navigate("approvals");
    else toast("当前没有新的待办", "info", 2000);
  });
  document.getElementById("user-chip").addEventListener("click", showAccountModal);
  document.getElementById("sidebar-logout").addEventListener("click", logout);
  refreshApprovalBadge();
}

async function refreshApprovalBadge() {
  if (!store.can("approvals")) return;
  try {
    const summary = await api.approvalSummary();
    store.setPendingApprovals(summary.pending || 0);
    const badges = document.querySelectorAll("[data-approval-badge]");
    badges.forEach((badge) => {
      badge.textContent = summary.pending || 0;
      badge.hidden = !summary.pending;
    });
    const dot = document.getElementById("bell-dot");
    if (dot) dot.hidden = !summary.pending;
  } catch {
    /* 静默失败，不影响页面 */
  }
}

function showAccountModal() {
  const user = store.user;
  const tenant = store.tenant || {};
  const communities = user.communities?.map((c) => c.name).join("、") || "全部";
  const { root, close } = openModal({
    title: "账号与数据范围",
    subtitle: "权限由服务端 RBAC 与社区授权共同决定",
    body: `<div class="row" style="gap:14px">
        ${avatar(user.display_name, user.role)}
        <div><b style="font-size:16px">${esc(user.display_name)}</b><div class="muted" style="font-size:12px">@${esc(user.username)} · ${esc(roleLabel(user.role))}</div></div>
      </div>
      <div class="divider"></div>
      <div class="info-grid">
        <div class="info-item"><span>租户</span><b>${esc(tenant.name || "—")}</b></div>
        <div class="info-item"><span>角色</span><b>${esc(roleLabel(user.role))}</b></div>
        <div class="info-item"><span>手机号</span><b>${esc(user.phone || "—")}</b></div>
        <div class="info-item"><span>社区范围</span><b>${esc(communities)}</b></div>
      </div>
      <div class="warning-box" style="margin-top:16px">前端菜单隐藏只改善体验，所有接口均由服务端再次校验角色与社区范围。</div>`,
    footer: `<button class="btn btn-ghost" data-close>关闭</button><button class="btn btn-danger-soft" id="account-logout">${icon("logout", 15)} 退出登录</button>`,
    onMount: (modal, closeFn) => {
      modal.querySelector("#account-logout").addEventListener("click", () => {
        closeFn();
        logout();
      });
    },
  });
  return root;
}

async function logout() {
  await store.logout();
  renderLogin();
  toast("已安全退出", "success", 2000);
}

/* ==========================================================================
   登录页
   ========================================================================== */
const DEMO_ACCOUNTS = [
  { username: "admin", name: "周明", role: "系统管理员", desc: "全部权限" },
  { username: "ops", name: "林晓", role: "运营人员", desc: "3 个社区" },
  { username: "tech", name: "陈工", role: "维修人员", desc: "工单处理" },
  { username: "finance", name: "赵敏", role: "财务审批", desc: "审批与执行" },
  { username: "resident", name: "王悦", role: "居民用户", desc: "本人订单" },
  { username: "resident2", name: "李然", role: "居民用户", desc: "两个社区" },
];

function renderLogin(message = "") {
  const accounts = DEMO_ACCOUNTS.map(
    (account) => `<button type="button" class="demo-account" data-demo="${account.username}">
      <b>${account.name} · ${account.role}</b><span>${account.username} / ${account.desc}</span>
    </button>`
  ).join("");
  app.innerHTML = `
    <div class="login-page">
      <section class="login-brand">
        <div class="login-brand-inner">
          <div class="login-logo"><span class="logo-mark"></span><span>邻里充电 · 运营平台</span></div>
          <div class="login-hero">
            <span class="login-eyebrow">Neighborhood Charging OS</span>
            <h1>让每一度电<br/>都<em>被看见</em>。</h1>
            <p>统一管理社区、充电桩、预约订单、设备事件与维修工单。Agent 在权限与审批边界内完成查询、归因与任务编排。</p>
            <div class="login-features">
              <div class="login-feature"><span class="feature-ico">${icon("activity", 17)}</span><div><b>实时运营态势</b><span>可用率、利用率、故障率与收入</span></div></div>
              <div class="login-feature"><span class="feature-ico">${icon("ticket", 17)}</span><div><b>故障闭环</b><span>事件去重、自动建单、验收关闭</span></div></div>
              <div class="login-feature"><span class="feature-ico">${icon("shield", 17)}</span><div><b>高风险审批</b><span>停机、退款、调价不直接执行</span></div></div>
              <div class="login-feature"><span class="feature-ico">${icon("agent", 17)}</span><div><b>Agent 工作台</b><span>工具白名单、trace_id 可追溯</span></div></div>
            </div>
          </div>
        </div>
        <div class="login-foot"><span>© 2026 邻里充电</span><span>多租户 · RBAC · 审计留痕</span></div>
      </section>
      <section class="login-panel">
        <div class="login-card">
          <span class="eyebrow">Welcome back</span>
          <h2>登录运营工作台</h2>
          <p class="sub">使用演示账号快速体验，或输入你的企业账号。</p>
          <form class="login-form" id="login-form" autocomplete="on">
            <div class="field">
              <label for="login-username">账号</label>
              <div class="input-icon">${icon("user", 16)}<input class="input" id="login-username" name="username" placeholder="请输入账号" autocomplete="username" required /></div>
            </div>
            <div class="field">
              <label for="login-password">密码</label>
              <div class="input-icon">${icon("lock", 16)}
                <input class="input" id="login-password" name="password" type="password" placeholder="请输入密码" autocomplete="current-password" required />
                <button class="pwd-toggle" type="button" id="pwd-toggle" aria-label="显示密码">${icon("eye", 17)}</button>
              </div>
            </div>
            <input type="hidden" name="tenant_code" value="NEIGHBOR" />
            <div class="login-meta">
              <label class="checkbox-row"><input type="checkbox" id="remember" checked /> 保持登录</label>
              <span class="muted">演示密码 Demo@2026</span>
            </div>
            <div class="form-error" id="login-error">${message ? esc(message) : ""}</div>
            <button class="btn btn-primary login-submit" type="submit" id="login-submit">${icon("arrowRight", 17)} 进入工作台</button>
          </form>
          <div class="login-divider">演示账号 · 一键填入</div>
          <div class="demo-accounts">${accounts}</div>
          <div class="login-note">${icon("info", 16)}<div>演示环境包含示例数据，所有高风险动作仍会进入审批流程。生产部署请关闭 DEMO_MODE 并替换 JWT_SECRET。</div></div>
        </div>
      </section>
    </div>`;

  const form = document.getElementById("login-form");
  const username = document.getElementById("login-username");
  const password = document.getElementById("login-password");
  const errorBox = document.getElementById("login-error");
  const submit = document.getElementById("login-submit");
  const pwdToggle = document.getElementById("pwd-toggle");

  document.querySelectorAll("[data-demo]").forEach((button) => {
    button.addEventListener("click", () => {
      username.value = button.dataset.demo;
      password.value = "Demo@2026";
      errorBox.textContent = "";
      username.focus();
      password.focus();
    });
  });
  pwdToggle.addEventListener("click", () => {
    const show = password.type === "password";
    password.type = show ? "text" : "password";
    pwdToggle.innerHTML = icon(show ? "eyeOff" : "eye", 17);
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    errorBox.textContent = "";
    if (!username.value.trim() || !password.value) {
      errorBox.textContent = "请输入账号和密码";
      return;
    }
    submit.disabled = true;
    submit.innerHTML = `<span class="typing"><span></span><span></span><span></span></span> 正在登录…`;
    try {
      await store.login({
        username: username.value.trim(),
        password: password.value,
        tenant_code: "NEIGHBOR",
        remember: document.getElementById("remember").checked,
      });
      renderShell();
      const target = parseHash();
      const allowed = store.state.menus;
      if (!allowed.includes(target.name)) location.hash = `#/${defaultRoute()}`;
      else renderRoute();
      toast(`欢迎回来，${store.user.display_name}`, "success", 2600);
    } catch (error) {
      errorBox.textContent = error.message || "登录失败，请检查账号密码";
      submit.disabled = false;
      submit.innerHTML = `${icon("arrowRight", 17)} 进入工作台`;
    }
  });
}

/* ==========================================================================
   路由
   ========================================================================== */
async function renderRoute(force = false) {
  if (!store.isAuthenticated) return;
  closeAllOverlays();
  const parsed = parseHash();
  const allowed = store.state.menus;
  if (!allowed.includes(parsed.name)) {
    if (force) return;
    location.hash = `#/${defaultRoute()}`;
    return;
  }
  const meta = PAGE_META[parsed.name] || PAGE_META.dashboard;
  const page = document.getElementById("page");
  if (!page) return;
  document.getElementById("topbar-title").textContent = meta.title;
  document.getElementById("crumb-current").textContent = meta.crumb;
  document.title = `${meta.title} · 邻里充电`;
  document.querySelectorAll("[data-nav]").forEach((link) => {
    link.classList.toggle("active", link.dataset.nav === parsed.name);
  });
  store.setRoute(parsed.name, parsed.query);
  const seq = ++renderSeq;
  page.innerHTML = `<div class="page-head"><div><span class="eyebrow">${esc(meta.crumb)}</span><h1>${esc(meta.title)}</h1><p class="sub">正在加载数据…</p></div></div>
    <div class="stack"><div class="skeleton sk-card" style="height:120px"></div><div class="grid grid-3"><div class="skeleton sk-card"></div><div class="skeleton sk-card"></div><div class="skeleton sk-card"></div></div></div>`;
  try {
    const mod = PAGES[parsed.name];
    if (!mod?.render) throw new Error("页面尚未实现");
    await mod.render(page, { query: parsed.query, refresh: () => renderRoute(true) });
    if (seq !== renderSeq) return;
    page.querySelectorAll("[data-link]").forEach((link) => {
      link.addEventListener("click", (event) => {
        event.preventDefault();
        navigate(link.dataset.link);
      });
    });
  } catch (error) {
    if (seq !== renderSeq) return;
    console.error(error);
    const trace = error.traceId ? `<div class="muted mono" style="font-size:10.5px;margin-top:8px">trace_id: ${esc(error.traceId)}</div>` : "";
    page.innerHTML = `<div class="page-head"><div><span class="eyebrow">${esc(meta.crumb)}</span><h1>${esc(meta.title)}</h1></div></div>
      <div class="card">${emptyState("alertCircle", "页面加载失败", error.message || "请稍后重试", `<button class="btn btn-primary" id="retry-page">${icon("refresh", 15)} 重新加载</button>`)}${trace}</div>`;
    document.getElementById("retry-page")?.addEventListener("click", () => renderRoute(true));
  }
}

/* ==========================================================================
   Boot
   ========================================================================== */
async function boot() {
  window.addEventListener("hashchange", () => renderRoute());
  window.addEventListener("auth:expired", () => {
    store.clear();
    renderLogin("登录已过期，请重新登录");
  });
  window.addEventListener("community:changed", () => {
    if (store.state.route.name !== "agent") renderRoute(true);
  });
  if (!tokens.access) {
    renderLogin();
    return;
  }
  try {
    await store.bootstrap();
    renderShell();
    if (!location.hash) location.hash = `#/${defaultRoute()}`;
    await renderRoute();
  } catch (error) {
    console.warn(error);
    tokens.clear();
    renderLogin(error.status === 401 ? "登录已过期，请重新登录" : "无法连接服务，请确认后端已启动");
  }
}

boot();

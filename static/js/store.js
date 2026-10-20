/* 全局状态：会话、数据范围、当前社区、Agent 会话 */

import { api, tokens, ApiError } from "./api.js";

const listeners = new Set();
const COMMUNITY_KEY = "nc_current_community";
const SESSION_KEY = "nc_agent_session";

function newSessionId() {
  const rand = Math.random().toString(36).slice(2, 10);
  return `sess_${Date.now().toString(36)}_${rand}`;
}

const state = {
  user: null,
  tenant: null,
  menus: [],
  communities: [],
  currentCommunityId: null,
  sessionId: localStorage.getItem(SESSION_KEY) || newSessionId(),
  route: { name: "dashboard", query: {} },
  sidebarOpen: false,
  pendingApprovals: 0,
  demoMode: false,
};

localStorage.setItem(SESSION_KEY, state.sessionId);

function emit() {
  listeners.forEach((fn) => {
    try {
      fn(state);
    } catch (error) {
      console.error(error);
    }
  });
}

export const store = {
  state,
  subscribe(fn) {
    listeners.add(fn);
    return () => listeners.delete(fn);
  },
  get user() {
    return state.user;
  },
  get isAuthenticated() {
    return Boolean(state.user && tokens.access);
  },
  get isStaff() {
    return ["admin", "operator", "technician", "finance"].includes(state.user?.role);
  },
  get isAdmin() {
    return state.user?.role === "admin";
  },
  get isResident() {
    return state.user?.role === "resident";
  },
  can(menu) {
    return state.menus.includes(menu);
  },
  hasRole(...roles) {
    return roles.includes(state.user?.role);
  },
  communityName(id = state.currentCommunityId) {
    if (!id) return "全部社区";
    return state.communities.find((c) => c.id === Number(id))?.name || "全部社区";
  },
  scopeQuery() {
    return state.currentCommunityId ? { community_id: state.currentCommunityId } : {};
  },

  async bootstrap() {
    if (!tokens.access) throw new ApiError("未登录", { status: 401, code: "NO_TOKEN" });
    const data = await api.me();
    state.user = data.user;
    state.tenant = data.tenant;
    state.menus = data.menus || [];
    state.demoMode = Boolean(data.demo_mode);
    const communityData = await api.communities();
    state.communities = communityData.items || [];
    const saved = Number(localStorage.getItem(COMMUNITY_KEY) || 0);
    const allowed = state.communities.some((c) => c.id === saved);
    state.currentCommunityId = allowed ? saved : null;
    if (state.communities.length === 1) {
      state.currentCommunityId = state.communities[0].id;
    }
    emit();
    return data;
  },

  async login(payload) {
    const data = await api.login(payload);
    state.user = data.user;
    state.tenant = data.tenant;
    state.menus = data.menus || [];
    state.demoMode = Boolean(data.demo_mode);
    try {
      const communityData = await api.communities();
      state.communities = communityData.items || [];
    } catch {
      state.communities = data.user?.communities || [];
    }
    const saved = Number(localStorage.getItem(COMMUNITY_KEY) || 0);
    state.currentCommunityId = state.communities.some((c) => c.id === saved) ? saved : null;
    if (state.communities.length === 1) state.currentCommunityId = state.communities[0].id;
    emit();
    return data;
  },

  async logout() {
    await api.logout();
    state.user = null;
    state.tenant = null;
    state.menus = [];
    state.communities = [];
    state.pendingApprovals = 0;
    emit();
  },

  clear() {
    tokens.clear();
    state.user = null;
    state.tenant = null;
    state.menus = [];
    state.communities = [];
    state.pendingApprovals = 0;
    emit();
  },

  setCommunity(id) {
    state.currentCommunityId = id ? Number(id) : null;
    localStorage.setItem(COMMUNITY_KEY, state.currentCommunityId || "");
    emit();
    window.dispatchEvent(new CustomEvent("community:changed", { detail: state.currentCommunityId }));
  },

  setRoute(name, query = {}) {
    state.route = { name, query };
    state.sidebarOpen = false;
  },

  toggleSidebar(open = !state.sidebarOpen) {
    state.sidebarOpen = open;
    emit();
  },

  setPendingApprovals(count) {
    state.pendingApprovals = Number(count || 0);
    emit();
  },

  newSession() {
    state.sessionId = newSessionId();
    localStorage.setItem(SESSION_KEY, state.sessionId);
    emit();
    return state.sessionId;
  },
};

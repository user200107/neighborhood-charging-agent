/* Agent 工作台：对话、工具轨迹、审批卡片与运行上下文 */

import { api } from "../api.js";
import { store } from "../store.js";
import {
  icon, esc, fmtDateTime, fmtRelative, statusBadge, toast,
} from "../ui.js";

const chatState = {
  messages: [],
  lastResult: null,
  handledPrompt: "",
  suggestions: [],
};

const DEFAULT_SUGGESTIONS = [
  "近 7 天运营情况怎么样？",
  "诊断 HP-A-02 的故障",
  "当前待处理工单有哪些？",
  "查一下云栖花园的空闲充电桩",
  "把 YQ-A-01 停机检修",
];

function formatAnswer(text) {
  const safe = esc(text || "")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
  return safe
    .split(/\n{2,}/)
    .map((block) => `<p>${block.replace(/\n/g, "<br/>")}</p>`)
    .join("");
}

function riskBadge(risk, label) {
  const cls = risk === "high_risk" ? "badge-amber" : risk === "normal_write" ? "badge-blue" : "badge-green";
  return `<span class="badge ${cls} no-dot">${esc(label || risk)}</span>`;
}

function statusBadgeAgent(status) {
  const map = {
    completed: ["已完成", "badge-green"],
    pending_approval: ["待审批 · 未执行", "badge-amber"],
    rejected: ["已拒绝", "badge-red"],
    failed: ["失败", "badge-red"],
  };
  const [label, cls] = map[status] || [status, "badge-slate"];
  return `<span class="badge ${cls} no-dot">${esc(label)}</span>`;
}

function messageHtml(message) {
  if (message.role === "user") {
    return `<div class="msg msg-user">
      <div class="msg-avatar">${icon("user", 15)}</div>
      <div class="msg-bubble">${formatAnswer(message.content)}<div class="msg-meta">${esc(message.at || "")}</div></div>
    </div>`;
  }
  if (message.role === "error") {
    return `<div class="msg msg-ai">
      <div class="msg-avatar">${icon("alertCircle", 16)}</div>
      <div class="msg-bubble" style="border-color:#f6cccc;background:#fff7f7"><p><strong>请求失败</strong></p><p>${esc(message.content)}</p></div>
    </div>`;
  }
  const result = message.result || {};
  const toolCalls = result.tool_calls || [];
  const sources = result.sources || [];
  const approval = result.approval;
  const toolTrace = toolCalls.length
    ? `<details class="tool-trace"><summary>${icon("terminal", 12)} 工具调用 ${toolCalls.length} 次 · ${esc(result.latency_ms || 0)} ms</summary>
        ${toolCalls
          .map(
            (call) => `<div class="tool-call">
              <div class="tc-top">${esc(call.label || call.name)} ${call.status === "success" ? `<span class="badge badge-green no-dot">成功</span>` : `<span class="badge badge-red no-dot">失败</span>`} <span class="muted" style="font-weight:400">${esc(call.duration_ms)}ms</span></div>
              <div class="tc-sum">${esc(call.summary || "")}</div>
              <div class="tc-args">${esc(JSON.stringify(call.args || {}))}</div>
            </div>`
          )
          .join("")}
      </details>`
    : "";
  const sourcesHtml = sources.length
    ? `<div class="msg-sources">${sources.map((source) => `<span>${icon("database", 10)} ${esc(source.name)}${source.count ? ` · ${source.count}` : ""}</span>`).join("")}</div>`
    : "";
  const approvalHtml = approval
    ? `<div class="approval-inline">
        <div class="ai-head">${icon("shield", 14)} ${esc(approval.status === "pending" ? "已创建审批，尚未执行" : "审批状态：" + approval.status)}</div>
        <div class="ai-body">${esc(approval.type_label)} · ${esc(approval.target_name || "")}<br/>影响范围：${esc(approval.impact_scope || "—")}${approval.amount ? ` · 金额 ¥${Number(approval.amount).toFixed(2)}` : ""}</div>
        <a href="#/approvals?id=${approval.id}">前往审批中心查看 ${icon("arrowRight", 12)}</a>
      </div>`
    : "";
  return `<div class="msg msg-ai">
      <div class="msg-avatar">${icon("agent", 17)}</div>
      <div class="msg-bubble">
        ${formatAnswer(result.answer || message.content)}
        <div class="msg-meta">
          ${statusBadgeAgent(result.status)}
          ${riskBadge(result.risk_level, result.risk_label)}
          <span>${esc(result.intent_label || result.intent || "")}</span>
          ${result.trace_id ? `<span class="trace">trace ${esc(result.trace_id)}</span>` : ""}
        </div>
        ${sourcesHtml}
        ${toolTrace}
        ${approvalHtml}
      </div>
    </div>`;
}

function welcomeHtml() {
  const suggestions = chatState.suggestions.length ? chatState.suggestions : DEFAULT_SUGGESTIONS;
  return `<div class="chat-welcome">
    <div class="cw-ico">${icon("agent", 26)}</div>
    <h2>今天想了解什么？</h2>
    <p>我可以查询运营指标、诊断设备故障、生成维修方案，也可以在高风险动作前帮你创建审批。所有回答都会标注数据来源与 trace_id。</p>
    <div class="prompt-grid">${suggestions
      .slice(0, 6)
      .map((prompt) => `<button class="prompt-chip" data-prompt="${esc(prompt)}">${icon("spark", 14)}<span>${esc(prompt)}</span></button>`)
      .join("")}</div>
  </div>`;
}

function contextPanelHtml(result) {
  const tools = result?.tool_calls || [];
  return `<div class="stack" style="gap:14px">
    <section class="card context-card">
      <h4>${icon("activity", 14)} 工作流节点</h4>
      <div class="context-list">
        ${[
          ["parse_intent", "意图识别"],
          ["load_context", "上下文检索"],
          ["check_permission", "权限与数据范围"],
          ["plan_action", "工具规划"],
          ["risk_gate", "风险分级"],
          ["execute_action", "执行 / 创建审批"],
          ["verify_result", "结果校验"],
          ["reflect", "生成回答"],
        ]
          .map(
            ([node, label], index) => `<div class="context-item"><span class="ci-node" style="background:${result ? "#10b981" : index < 2 && result === null ? "#cbd5e1" : "#cbd5e1"}"></span><div><b>${label}</b><span class="mono" style="font-size:9px">${node}</span></div></div>`
          )
          .join("")}
      </div>
    </section>
    <section class="card context-card">
      <h4>${icon("terminal", 14)} 本次运行</h4>
      <div class="context-list" style="gap:0">
        <div class="context-kv"><span>会话</span><b class="mono" style="font-size:9.5px">${esc(store.state.sessionId)}</b></div>
        <div class="context-kv"><span>数据范围</span><b>${esc(store.communityName())}</b></div>
        <div class="context-kv"><span>意图</span><b>${esc(result?.intent_label || "—")}</b></div>
        <div class="context-kv"><span>风险</span><b>${esc(result?.risk_label || "—")}</b></div>
        <div class="context-kv"><span>状态</span><b>${esc(result?.status || "—")}</b></div>
        <div class="context-kv"><span>耗时</span><b>${result ? `${result.latency_ms} ms` : "—"}</b></div>
        <div class="context-kv"><span>trace_id</span><b class="mono" style="font-size:9px">${esc(result?.trace_id || "—")}</b></div>
      </div>
    </section>
    <section class="card context-card">
      <h4>${icon("shield", 14)} 安全边界</h4>
      <div class="rule-list">
        <div class="rule-item">${icon("checkCircle", 14)} 只读查询直接执行，并返回数据来源。</div>
        <div class="rule-item">${icon("checkCircle", 14)} 普通写入幂等执行并记录审计。</div>
        <div class="rule-item">${icon("shield", 14)} 停机、退款、调价、批量改派只创建审批。</div>
        <div class="rule-item">${icon("lock", 14)} 模型不能执行 SQL 或系统命令，工具参数经 Pydantic 校验。</div>
      </div>
    </section>
    ${tools.length ? `<section class="card context-card"><h4>${icon("cpu", 14)} 最近工具</h4><div class="context-list">${tools.map((tool) => `<div class="context-item"><span class="ci-node" style="background:${tool.status === "success" ? "#10b981" : "#ef4444"}"></span><div><b>${esc(tool.label || tool.name)}</b><span>${esc(tool.duration_ms)} ms · ${esc(tool.status)}</span></div></div>`).join("")}</div></section>` : ""}
    <section class="card context-card">
      <h4>${icon("info", 14)} 说明</h4>
      <p class="hint" style="margin-top:8px">${store.isResident ? "居民账号可以查询可用枪口、本人订单与指标解释；高风险动作会被拒绝。" : "Agent 使用白名单工具访问业务数据，回答仅基于工具结果，不会编造执行结果。"}</p>
    </section>
  </div>`;
}

export async function render(page, ctx) {
  if (!chatState.suggestions.length) {
    try {
      const data = await api.agentSuggestions();
      chatState.suggestions = data.items || [];
    } catch {
      chatState.suggestions = DEFAULT_SUGGESTIONS;
    }
  }
  const sessionId = store.state.sessionId;
  page.innerHTML = `
    <div class="page-head">
      <div>
        <span class="eyebrow">智能运营</span>
        <h1>Agent 工作台</h1>
        <p class="sub">自然语言查询、故障归因、维修方案与任务编排 · 高风险动作转审批</p>
      </div>
      <div class="page-actions">
        <span class="badge badge-green no-dot">${icon("shield", 12)} 工具白名单</span>
        <button class="btn btn-ghost btn-sm" id="agent-new-session">${icon("plus", 14)} 新建会话</button>
      </div>
    </div>
    <div class="agent-layout">
      <section class="card chat-card">
        <div class="chat-head">
          <div class="agent-avatar">${icon("agent", 20)}</div>
          <div><b>邻里运营助手</b><span><span class="online-dot"></span> 在线 · 规则引擎 + 可选 LLM · 高风险需审批</span></div>
          <div class="head-actions"><span class="badge badge-slate no-dot mono" style="font-size:9px">${esc(sessionId)}</span></div>
        </div>
        <div class="chat-body" id="chat-body">
          ${chatState.messages.length ? chatState.messages.map(messageHtml).join("") : welcomeHtml()}
        </div>
        <div class="chat-input-area">
          <div class="chat-input-box">
            <textarea id="agent-input" rows="1" placeholder="问我运营数据、故障原因，或发起一个需要审批的动作…"></textarea>
            <button class="send-btn" id="agent-send" aria-label="发送">${icon("send", 17)}</button>
          </div>
          <div class="chat-footnote"><span>Enter 发送 · Shift + Enter 换行</span><span>回答由工具结果生成，执行状态以审批/审计为准</span></div>
        </div>
      </section>
      <aside class="agent-side">${contextPanelHtml(chatState.lastResult)}</aside>
    </div>`;

  const body = document.getElementById("chat-body");
  const input = document.getElementById("agent-input");
  const send = document.getElementById("agent-send");
  const scrollBottom = () => {
    body.scrollTop = body.scrollHeight;
  };
  if (chatState.messages.length) scrollBottom();
  else body.scrollTop = 0;

  document.getElementById("agent-new-session").addEventListener("click", () => {
    chatState.messages = [];
    chatState.lastResult = null;
    chatState.handledPrompt = "";
    store.newSession();
    render(page, ctx);
    toast("已开启新的 Agent 会话", "success", 2000);
  });

  const sendMessage = async () => {
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    input.style.height = "auto";
    chatState.messages.push({ role: "user", content: text, at: fmtRelative(new Date().toISOString()) });
    body.innerHTML = chatState.messages.map(messageHtml).join("") + `<div class="msg msg-ai" id="typing-msg"><div class="msg-avatar">${icon("agent", 17)}</div><div class="msg-bubble"><span class="typing"><span></span><span></span><span></span></span> 正在分析…</div></div>`;
    scrollBottom();
    input.disabled = true;
    send.disabled = true;
    try {
      const result = await api.agentChat({
        message: text,
        session_id: store.state.sessionId,
        community_id: store.state.currentCommunityId || undefined,
      });
      chatState.lastResult = result;
      chatState.messages.push({ role: "assistant", content: result.answer, result });
      body.innerHTML = chatState.messages.map(messageHtml).join("");
      scrollBottom();
      const aside = page.querySelector(".agent-side");
      if (aside) aside.innerHTML = contextPanelHtml(result);
      if (result.status === "pending_approval") {
        toast("高风险动作已转审批，尚未执行", "warn", 4200);
      }
    } catch (error) {
      chatState.messages.push({ role: "error", content: error.message });
      body.innerHTML = chatState.messages.map(messageHtml).join("");
      toast(error.message, "error");
    } finally {
      input.disabled = false;
      send.disabled = false;
      input.focus({ preventScroll: true });
      scrollBottom();
    }
  };

  send.addEventListener("click", sendMessage);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendMessage();
    }
  });
  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = `${Math.min(130, input.scrollHeight)}px`;
  });
  body.querySelectorAll("[data-prompt]").forEach((button) => {
    button.addEventListener("click", () => {
      input.value = button.dataset.prompt;
      sendMessage();
    });
  });

  const prompt = ctx.query.prompt;
  if (prompt && prompt !== chatState.handledPrompt) {
    chatState.handledPrompt = prompt;
    input.value = prompt;
    setTimeout(sendMessage, 180);
  }
  input.focus({ preventScroll: true });
}

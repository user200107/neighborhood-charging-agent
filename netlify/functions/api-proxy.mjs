/**
 * Netlify Function：将 /api/* 反向代理到 FastAPI。
 *
 * 说明：Netlify 不支持 Python Functions，FastAPI 需部署在支持 Python 的
 * 服务（Render / Railway / Fly.io / 自建容器）上。此代理保持浏览器同源，
 * 避免 CORS 与后端地址暴露，并能统一追加安全头。
 *
 * 环境变量：API_BASE_URL（必填，示例 https://charging-api.onrender.com）
 */

const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
  "host",
  "content-length",
]);

function json(status, payload) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

export default async (req) => {
  const base = (process.env.API_BASE_URL || "")
    .trim()
    .replace(/\/+$/, "")
    .replace(/\/api$/, "");
  if (!base) {
    return json(503, {
      detail: "后端未配置：请在 Netlify 环境变量中设置 API_BASE_URL",
      code: "API_NOT_CONFIGURED",
      trace_id: null,
    });
  }

  const incoming = new URL(req.url);
  const target = `${base}${incoming.pathname}${incoming.search}`;
  const headers = new Headers();
  for (const [key, value] of req.headers.entries()) {
    if (!HOP_BY_HOP.has(key.toLowerCase())) headers.set(key, value);
  }
  headers.set("x-forwarded-host", incoming.host);
  headers.set("x-forwarded-proto", incoming.protocol.replace(":", "") || "https");
  const clientIp = req.headers.get("x-nf-client-connection-ip");
  if (clientIp) headers.set("x-forwarded-for", clientIp);

  const init = {
    method: req.method,
    headers,
    redirect: "manual",
  };
  if (!["GET", "HEAD"].includes(req.method)) {
    init.body = await req.arrayBuffer();
  }

  let upstream;
  try {
    upstream = await fetch(target, init);
  } catch (error) {
    return json(502, {
      detail: "无法连接后端服务，请检查 API_BASE_URL 或后端健康状态",
      code: "UPSTREAM_UNREACHABLE",
      trace_id: null,
    });
  }

  const responseHeaders = new Headers();
  for (const [key, value] of upstream.headers.entries()) {
    if (!["content-encoding", "content-length", "transfer-encoding"].includes(key.toLowerCase())) {
      responseHeaders.set(key, value);
    }
  }
  responseHeaders.set("x-proxied-by", "netlify-function");
  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders,
  });
};

export const config = {
  path: ["/api/*"],
};

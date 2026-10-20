"""Netlify 静态构建。

将 static/ 复制到 dist/static，并把 index.html 放到 dist 根目录。
不依赖 Node/npm，Netlify 构建镜像自带 Python 即可执行。
"""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
DIST = ROOT / "dist"

HEADERS = """\
/static/*
  Cache-Control: public, max-age=31536000, immutable
  X-Content-Type-Options: nosniff
  X-Frame-Options: SAMEORIGIN

/index.html
  Cache-Control: no-cache

/*
  X-Content-Type-Options: nosniff
  X-Frame-Options: SAMEORIGIN
  Referrer-Policy: strict-origin-when-cross-origin
  Permissions-Policy: camera=(), microphone=(), geolocation=()
  Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'self'; frame-ancestors 'self'; base-uri 'self'; form-action 'self'
"""


def main() -> None:
    if not (STATIC / "index.html").exists():
        raise SystemExit("static/index.html 不存在")

    if DIST.exists():
        shutil.rmtree(DIST)
    (DIST / "static").mkdir(parents=True)

    for item in STATIC.iterdir():
        target = DIST / "static" / item.name
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)

    shutil.copy2(STATIC / "index.html", DIST / "index.html")
    (DIST / "_headers").write_text(HEADERS, encoding="utf-8")
    (DIST / "robots.txt").write_text(
        "User-agent: *\nDisallow: /\n", encoding="utf-8"
    )

    # 运行时配置：API 经 Netlify Function / 同源代理访问，不暴露后端地址
    config = (
        "/* 由 scripts/build_netlify.py 生成 */\n"
        "window.__APP_CONFIG__ = {\n"
        '  apiBaseUrl: "",\n'
        '  env: "production",\n'
        '  version: "1.0.0",\n'
        '  delivery: "netlify",\n'
        "};\n"
    )
    (DIST / "static" / "config.js").write_text(config, encoding="utf-8")

    files = sum(1 for path in DIST.rglob("*") if path.is_file())
    print(f"Netlify build complete: {files} files -> {DIST}")


if __name__ == "__main__":
    main()

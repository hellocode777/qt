#!/bin/bash
# SPA 原型部署: 构建 → 拷贝到 qp/web/static/spa (由 FastAPI /proto 挂载)
# 用法: bash scripts/spa_deploy.sh
# 前端源码就在本仓库 qp/web/spa_src/（可用 QP_PROTO_WEB 覆盖，指向别处的 web 目录）
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROTO_WEB="${QP_PROTO_WEB:-$REPO_ROOT/qp/web/spa_src}"
SPA_DIR="$REPO_ROOT/qp/web/static/spa"

if [ ! -f "$PROTO_WEB/package.json" ]; then
  echo "❌ 找不到前端源码: $PROTO_WEB/package.json" >&2
  echo "   （首次在新机器上跑需先: cd $PROTO_WEB && npm install）" >&2
  exit 1
fi
if [ ! -d "$PROTO_WEB/node_modules" ]; then
  echo "❌ 缺少 node_modules: cd $PROTO_WEB && npm install" >&2
  exit 1
fi

echo "[1/3] 前端 build (base=/proto/)"
( cd "$PROTO_WEB" && npm run build )

echo "[2/3] 拷贝 dist → $SPA_DIR"
mkdir -p "$SPA_DIR"
rm -rf "$SPA_DIR"/* "$SPA_DIR"/.[!.]* 2>/dev/null || true
cp -r "$PROTO_WEB/dist/"* "$SPA_DIR"/ 2>/dev/null || true

echo "[3/3] 完成"
echo "访问: http://127.0.0.1:8080/proto/  (qp web 若没在 --reload 模式需手动重启)"
echo "文件: $SPA_DIR"
find "$SPA_DIR" -type f | sed "s|$SPA_DIR/||" | head

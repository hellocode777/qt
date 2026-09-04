#!/bin/bash
# SPA 原型部署: 构建 → 拷贝到 qp/web/static/spa (由 FastAPI /proto 挂载)
# 用法: bash scripts/spa_deploy.sh
set -euo pipefail

PROTO_WEB="${QP_PROTO_WEB:-$HOME/workspace/quant-ui-research/qp-proto/web}"
SPA_DIR="$(cd "$(dirname "$0")/.." && pwd)/qp/web/static/spa"

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

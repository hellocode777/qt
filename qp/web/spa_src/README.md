# qp/web/spa_src — QP Terminal 原型前端源码

Vue 3 + Vite 单页应用（SPA），构建产物部署到 `qp/web/static/spa/`，由 FastAPI 挂在
`/proto/`（见 `qp/web/app.py` `_register_spa_routes`）。数据全部来自同进程的
`/api/v1/*`（`qp/web/routers/api_v1.py`）与 `/api/stocks/{code}/kline`
（`qp/web/routers/stocks.py`）—— 前端不含任何 mock 数据。

## 构建 + 部署

    cd ~/workspace/qt
    bash scripts/spa_deploy.sh      # npm run build → 拷贝 dist/* → qp/web/static/spa/

`qp/web/static/spa/`（构建产物）与 `qp/web/spa_src/{node_modules,dist}` 都在
`.gitignore` 里；入库的只有本目录的源码。

新机器首次使用：

    cd qp/web/spa_src && npm install     # 需要网络
    cd - && bash scripts/spa_deploy.sh

`spa_deploy.sh` 会用 `QP_PROTO_WEB` 覆盖源码目录（默认就是本目录）。

## 本地开发（带热更新，不碰 8080）

    npm run dev        # http://127.0.0.1:5173 ，vite 把 /api 代理到 8080

后端改了要生效：`qp web start --reload` 会自动重载；静态产物是逐请求读盘的，
重新 build 后浏览器刷新（必要时 Ctrl+Shift+R）即可，不用重启后端。

## 页面

`src/pages/` 11 页：Dashboard(总览) / Experiments(回测) / Simulation(影子) /
Paper(模拟盘) / Positions(持仓) / Chart(行情) / Strategies / Factors /
Decisions(决策) / SystemHealth / Knowledge；路由见 `src/App.vue`，端点封装见 `src/api.js`。

## 显示口径铁律（与 WebUI 一致）

后端拿不到的值返回 `None`，前端显示 `—`/`N/A`，**不得回落为 0**；
数字必须标注口径与数据日期。示例：`/api/v1/positions` 的 `pnl`/`pnl_pct` 是
**已实现盈亏**（平仓才结算），持仓行的盈亏要用 `unrealized_pnl`/
`unrealized_pnl_pct`（最新收盘标记，**小数**口径，0.1333 = +13.33%）。

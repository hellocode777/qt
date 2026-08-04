"""Simulation router — Shadow Production performance tracking.

GET "/simulation" — Shadow portfolio overview with:
  - Cumulative P&L chart
  - Daily performance history
  - Active shadow positions
  - Benchmark comparison
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from loguru import logger

from qp.web.routers._templates import templates

router = APIRouter(tags=["simulation"])


@router.get("/simulation/debug-chart", response_class=HTMLResponse)
async def debug_chart() -> str:
    """Standalone page to test canvas chart rendering."""
    from qp.simulation.shadow_ledger import ShadowLedger

    ledger = ShadowLedger()
    history = ledger.summary().get("history", [])
    import json

    equity_data = json.dumps(
        [
            {
                "date": h["date"],
                "total_equity": h["total_equity"],
                "market_value": h.get("market_value", 0),
            }
            for h in history
        ]
    )

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Chart Debug</title></head>
<body style="margin:20px;font-family:sans-serif;">
  <h2>Chart Debug — equity_data: {len(history)} rows</h2>
  <div style="width:800px;height:300px;border:2px solid red;">
    <canvas id="equityChart"></canvas>
  </div>
  <pre id="debug" style="margin-top:20px;background:#f5f5f5;padding:10px;"></pre>
  <script type="application/json" id="equity-data">{equity_data}</script>
  <script>
    var dbg = document.getElementById('debug');
    function log(msg) {{ dbg.textContent += msg + '\\n'; }}
    try {{
      var canvas = document.getElementById('equityChart');
      log('canvas: ' + !!canvas);
      log('parent size: ' + canvas.parentElement.offsetWidth + 'x' + canvas.parentElement.offsetHeight);

      var el = document.getElementById('equity-data');
      var rawData = JSON.parse(el.textContent || '[]');
      log('data rows: ' + rawData.length);

      var W = canvas.parentElement.clientWidth;
      var H = canvas.parentElement.clientHeight;
      canvas.width = W;
      canvas.height = H;
      canvas.style.width = W + 'px';
      canvas.style.height = H + 'px';

      var ctx = canvas.getContext('2d');
      log('ctx: ' + !!ctx);

      // Fill background
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(0, 0, W, H);
      log('fillRect done');

      // Draw a big red circle
      ctx.fillStyle = '#ff0000';
      ctx.beginPath();
      ctx.arc(W/2, H/2, 50, 0, Math.PI*2);
      ctx.fill();
      log('circle drawn at ' + W/2 + ',' + H/2 + ' r=50');

      // Draw text
      ctx.fillStyle = '#000000';
      ctx.font = '20px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('TEST CHART — ¥' + rawData[0].total_equity, W/2, H/2 - 70);
      log('text drawn');
      log('DONE — you should see a red circle and text');
    }} catch(e) {{
      log('ERROR: ' + e.message);
    }}
  </script>
</body></html>"""


@router.get("/simulation")
async def shadow_dashboard(request: Request) -> Any:
    """Shadow production performance dashboard."""
    from qp.simulation.shadow_ledger import ShadowLedger

    ledger = ShadowLedger()
    summary = ledger.summary()
    history = summary.get("history", [])

    # Compute benchmark comparison (CSI 300 proxy: just show absolute for now)
    trading_days = len(history)
    total_return = summary.get("total_return", 0)

    # Build equity curve data for Chart.js
    equity_data = [
        {
            "date": h["date"],
            "total_equity": h["total_equity"],
            "market_value": h.get("market_value", 0),
        }
        for h in history
    ]

    logger.info("Shadow dashboard: {} days, return={:.2%}", trading_days, total_return)

    return templates.TemplateResponse(
        request=request,
        name="simulation.html",
        context={
            "summary": summary,
            "history": history,
            "trading_days": trading_days,
            "total_return": total_return,
            "total_return_fmt": f"{total_return:+.2%}",
            "equity_data": json.dumps(equity_data),
            "has_data": len(history) > 0,
            "page_title": "Shadow Production — QP Decision Center",
        },
    )

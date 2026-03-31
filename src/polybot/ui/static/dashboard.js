async function refreshAll() {
  try {
    const res = await fetch("/api/metrics", { cache: "no-store" });
    if (!res.ok) return;
    const data = await res.json();
    const stats = data.stats || {};
    const positions = data.open_positions || [];

    const setText = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.textContent = val;
    };

    // KPI cards
    setText("kpi-decisions", stats.decisions_total ?? 0);
    setText("kpi-trades", stats.executed ?? 0);
    setText("kpi-usdc", stats.traded_usdc ?? 0);
    setText("kpi-edge", stats.avg_edge ?? 0);
    setText("kpi-conf", stats.avg_confidence ?? 0);
    setText("kpi-brier", stats.avg_brier_score ?? 0);

    // Status bar
    setText("live-pos-count", positions.length);

    // Refresh indicator
    const indicator = document.getElementById("refresh-indicator");
    if (indicator) {
      indicator.textContent = "更新于 " + new Date().toLocaleTimeString("zh-CN");
    }

    // Bankroll from equity curve
    const curve = data.equity_curve || [];
    if (curve.length > 0) {
      const lastBankroll = curve[curve.length - 1].bankroll;
      setText("live-bankroll", (lastBankroll ?? 10000).toFixed(2) + " USDC");
    }

    // Refresh pulse chip
    const chip = document.querySelector(".pulse-chip");
    if (chip) {
      const now = new Date().toLocaleTimeString("zh-CN");
      chip.textContent = `最后刷新 ${now}`;
    }

  } catch (_err) {
    // Silent on transient errors
  }
}

async function refreshPositionsPnl() {
  try {
    const res = await fetch("/api/positions-pnl", { cache: "no-store" });
    if (!res.ok) return;
    const positions = await res.json();
    const tbody = document.getElementById("positions-tbody");
    const countEl = document.getElementById("positions-count");
    const totalPnlEl = document.getElementById("positions-total-pnl");
    if (!tbody) return;

    if (countEl) countEl.textContent = positions.length;

    let totalPnl = 0;
    let html = "";
    for (const p of positions) {
      const pnl = p.live_pnl ?? 0;
      const pnlPct = p.live_pnl_pct ?? 0;
      totalPnl += pnl;
      const pnlClass = pnl >= 0 ? "text-green" : "text-red";
      const pnlSign = pnl >= 0 ? "+" : "";
      const sideClass = p.side === "BUY_YES" ? "text-green" : "text-red";
      html += `<tr>
        <td class="question" title="${p.question || p.market_id}">${p.question || p.market_id}</td>
        <td class="${sideClass}">${p.side}</td>
        <td>${p.entry_price}</td>
        <td>${p.live_price ?? p.current_price}</td>
        <td>${p.size_usdc} USDC</td>
        <td class="${pnlClass}"><b>${pnlSign}${pnl.toFixed(2)}</b> (${pnlSign}${pnlPct.toFixed(1)}%)</td>
        <td>${p.stop_loss_price}</td>
        <td>${p.take_profit_price}</td>
        <td>${p.opened_at ? p.opened_at.slice(0, 16) : ""}</td>
      </tr>`;
    }
    tbody.innerHTML = html || '<tr><td colspan="9" class="note">当前无持仓</td></tr>';

    if (totalPnlEl) {
      const sign = totalPnl >= 0 ? "+" : "";
      totalPnlEl.className = totalPnl >= 0 ? "text-green" : "text-red";
      totalPnlEl.textContent = `总盈亏: ${sign}${totalPnl.toFixed(2)} USDC`;
    }
  } catch (_err) {
    // Silent
  }
}

function refresh15s() {
  refreshAll();
  refreshPositionsPnl();
}

// Auto-refresh every 15 seconds
setInterval(refresh15s, 15000);
refresh15s();

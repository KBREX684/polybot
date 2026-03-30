async function refreshBadge() {
  try {
    const res = await fetch("/api/metrics", { cache: "no-store" });
    if (!res.ok) return;
    const data = await res.json();
    const chip = document.querySelector(".pulse-chip");
    if (!chip) return;
    const value = data?.stats?.decisions_total ?? 0;
    chip.textContent = `Live Audit Trail · ${value} decisions`;
  } catch (_err) {
    // Keep UI silent on transient refresh issues.
  }
}

setInterval(refreshBadge, 8000);
refreshBadge();

// ============================================================================
// Suretyscore front-end logic
// Same-origin ke FastAPI (di-serve oleh StaticFiles pada app yang sama).
// Jika frontend di-hosting terpisah dari backend, ubah API_BASE di bawah ini
// mis. const API_BASE = "http://localhost:8000";
// ============================================================================
const API_BASE = "";

const form = document.getElementById("scoreForm");
const submitBtn = document.getElementById("submitBtn");

const resultEmpty = document.getElementById("resultEmpty");
const resultLoading = document.getElementById("resultLoading");
const resultError = document.getElementById("resultError");
const resultErrorText = document.getElementById("resultErrorText");
const resultContent = document.getElementById("resultContent");

const gaugeScoreEl = document.getElementById("gaugeScore");
const needleGroup = document.getElementById("needleGroup");
const decisionBadge = document.getElementById("decisionBadge");
const decisionText = document.getElementById("decisionText");
const probaLine = document.getElementById("probaLine");
const breakdownList = document.getElementById("breakdownList");
const factorsList = document.getElementById("factorsList");

const CATEGORY_LABEL = {
  Character: "Character",
  Capital: "Capital",
  Capacity: "Capacity",
  Collateral: "Collateral",
  Condition: "Condition",
};

// ---------------------------------------------------------------------------
// Cek status API saat halaman dimuat
// ---------------------------------------------------------------------------
async function checkApiHealth() {
  const dot = document.getElementById("apiDot");
  const text = document.getElementById("apiStatusText");
  try {
    const res = await fetch(`${API_BASE}/api/health`);
    if (!res.ok) throw new Error("not ok");
    dot.classList.add("online");
    text.textContent = "API terhubung";
  } catch (err) {
    dot.classList.add("offline");
    text.textContent = "API tidak terhubung";
  }
}
checkApiHealth();

// ---------------------------------------------------------------------------
// Segmented control (toggle biner) -> sinkron ke hidden input
// ---------------------------------------------------------------------------
document.querySelectorAll(".segmented").forEach((group) => {
  const hiddenInput = group.parentElement.querySelector('input[type="hidden"]');
  group.querySelectorAll(".seg-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      group.querySelectorAll(".seg-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      hiddenInput.value = btn.dataset.value;
    });
  });
});

// ---------------------------------------------------------------------------
// Preview format Rupiah untuk field nominal besar
// ---------------------------------------------------------------------------
function formatRupiah(num) {
  if (isNaN(num)) return "Rp 0";
  return "Rp " + Math.round(num).toLocaleString("id-ID");
}
document.querySelectorAll(".currency-preview").forEach((preview) => {
  const fieldName = preview.dataset.previewFor;
  const input = form.querySelector(`[name="${fieldName}"]`);
  if (!input) return;
  const update = () => { preview.textContent = formatRupiah(parseFloat(input.value)); };
  input.addEventListener("input", update);
  update();
});

// ---------------------------------------------------------------------------
// Slider persentase penjaminan -> label live
// ---------------------------------------------------------------------------
const pctInput = form.querySelector('[name="Persentase_Penjaminan"]');
const pctLabel = document.getElementById("pctLabel");
pctInput.addEventListener("input", () => {
  pctLabel.textContent = `${pctInput.value}%`;
});

// ---------------------------------------------------------------------------
// Submit form -> panggil /api/score
// ---------------------------------------------------------------------------
form.addEventListener("submit", async (e) => {
  e.preventDefault();

  const formData = new FormData(form);
  const payload = {
    SLIK_OJK_Direksi: parseInt(formData.get("SLIK_OJK_Direksi"), 10),
    Riwayat_Klaim: parseFloat(formData.get("Riwayat_Klaim")),
    Lama_Operasional: parseFloat(formData.get("Lama_Operasional")),
    Hubungan_Supplier: parseInt(formData.get("Hubungan_Supplier"), 10),
    Current_Ratio: parseFloat(formData.get("Current_Ratio")),
    Debt_to_Equity_Ratio_DER: parseFloat(formData.get("Debt_to_Equity_Ratio_DER")),
    Net_Profit_Margin_NPM: parseFloat(formData.get("Net_Profit_Margin_NPM")),
    Return_on_Asset_ROA: parseFloat(formData.get("Return_on_Asset_ROA")),
    Lama_Penjaminan: parseFloat(formData.get("Lama_Penjaminan")),
    Jumlah_Proyek_Berjalan: parseInt(formData.get("Jumlah_Proyek_Berjalan"), 10),
    Nilai_Agunan: parseFloat(formData.get("Nilai_Agunan")),
    Jenis_Bond: formData.get("Jenis_Bond"),
    Nilai_Proyek: parseFloat(formData.get("Nilai_Proyek")),
    Persentase_Penjaminan: parseFloat(formData.get("Persentase_Penjaminan")),
    Jenis_Proyek: formData.get("Jenis_Proyek"),
  };

  setState("loading");
  submitBtn.disabled = true;

  try {
    const res = await fetch(`${API_BASE}/api/score`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      throw new Error(errBody.detail || `Server merespons status ${res.status}`);
    }

    const data = await res.json();
    renderResult(data);
    setState("content");
  } catch (err) {
    resultErrorText.textContent = `Gagal menghitung skor: ${err.message}`;
    setState("error");
  } finally {
    submitBtn.disabled = false;
  }
});

function setState(state) {
  resultEmpty.classList.add("hidden");
  resultLoading.classList.add("hidden");
  resultError.classList.add("hidden");
  resultContent.classList.add("hidden");

  if (state === "loading") resultLoading.classList.remove("hidden");
  if (state === "error") resultError.classList.remove("hidden");
  if (state === "content") resultContent.classList.remove("hidden");
  if (state === "empty") resultEmpty.classList.remove("hidden");
}

// ---------------------------------------------------------------------------
// Render hasil ke panel kanan
// ---------------------------------------------------------------------------
function renderResult(data) {
  // Gauge
  const score = data.skor_kelayakan;
  gaugeScoreEl.textContent = Math.round(score);
  const angle = -90 + (Math.max(0, Math.min(1000, score)) / 1000) * 180;
  needleGroup.style.transform = `rotate(${angle}deg)`;

  // Badge keputusan
  decisionText.textContent = data.keputusan;
  decisionBadge.classList.remove("approve", "review", "reject");
  if (data.keputusan.includes("Approve")) decisionBadge.classList.add("approve");
  else if (data.keputusan.includes("Reject")) decisionBadge.classList.add("reject");
  else decisionBadge.classList.add("review");

  probaLine.textContent =
    `Probabilitas default: ${(data.proba_default * 100).toFixed(1)}%` +
    ` · threshold bisnis: ${(data.threshold_bisnis * 100).toFixed(1)}%`;

  // Breakdown per 5C (diverging bar, dinormalisasi terhadap kontribusi absolut terbesar)
  const maxAbs = Math.max(...data.breakdown_5c.map((d) => Math.abs(d.kontribusi_total)), 0.001);
  breakdownList.innerHTML = "";
  data.breakdown_5c.forEach((item) => {
    const pct = Math.min(100, (Math.abs(item.kontribusi_total) / maxAbs) * 100);
    const isRisk = item.kontribusi_total > 0;
    const li = document.createElement("li");
    li.className = "breakdown-row";
    li.innerHTML = `
      <span class="cat-label">${CATEGORY_LABEL[item.kategori] || item.kategori}</span>
      <span class="bar-track">
        <span class="bar-mid"></span>
        <span class="bar-fill ${isRisk ? "risk-up" : "risk-down"}" style="width:${pct / 2}%"></span>
      </span>
      <span class="cat-value">${item.kontribusi_total > 0 ? "+" : ""}${item.kontribusi_total.toFixed(2)}</span>
    `;
    breakdownList.appendChild(li);
  });

  // Faktor individual teratas
  factorsList.innerHTML = "";
  data.top_faktor.forEach((f) => {
    const isUp = f.arah === "menaikkan";
    const li = document.createElement("li");
    li.className = "factor-row";
    li.innerHTML = `
      <span class="factor-arrow ${isUp ? "up" : "down"}">${isUp ? "▲" : "▼"}</span>
      <span class="factor-info">
        <span class="factor-label">${f.label}</span>
        <span class="factor-tag">${f.kategori}</span>
      </span>
      <span class="factor-value">${f.kontribusi > 0 ? "+" : ""}${f.kontribusi.toFixed(3)}</span>
    `;
    factorsList.appendChild(li);
  });

  // Scroll ke hasil pada layar sempit
  if (window.innerWidth <= 1024) {
    document.getElementById("resultPanel").scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

// ============================================================================
// FITUR: Analisis Kualitatif 5C (Gemini API)
// ============================================================================

// ---------------------------------------------------------------------------
// 1. Reputasi & Daftar Hitam
// ---------------------------------------------------------------------------
const reputationForm = document.getElementById("reputationForm");
const reputationBtn = document.getElementById("reputationBtn");
const reputationEmpty = document.getElementById("reputationEmpty");
const reputationLoading = document.getElementById("reputationLoading");
const reputationError = document.getElementById("reputationError");
const reputationContent = document.getElementById("reputationContent");

function setQualState(prefix, state, errorMsg) {
  document.getElementById(`${prefix}Empty`).classList.add("hidden");
  document.getElementById(`${prefix}Loading`).classList.add("hidden");
  document.getElementById(`${prefix}Error`).classList.add("hidden");
  document.getElementById(`${prefix}Content`).classList.add("hidden");

  if (state === "empty") document.getElementById(`${prefix}Empty`).classList.remove("hidden");
  if (state === "loading") document.getElementById(`${prefix}Loading`).classList.remove("hidden");
  if (state === "content") document.getElementById(`${prefix}Content`).classList.remove("hidden");
  if (state === "error") {
    const el = document.getElementById(`${prefix}Error`);
    el.textContent = errorMsg || "Terjadi kesalahan.";
    el.classList.remove("hidden");
  }
}

reputationForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(reputationForm);
  const payload = {
    nama_perusahaan: fd.get("nama_perusahaan").trim(),
    sektor: fd.get("sektor").trim(),
    lokasi: fd.get("lokasi").trim(),
  };

  setQualState("reputation", "loading");
  reputationBtn.disabled = true;

  try {
    const res = await fetch(`${API_BASE}/api/qualitative/reputation`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      throw new Error(errBody.detail || `Server merespons status ${res.status}`);
    }
    const data = await res.json();
    renderReputationResult(data);
    setQualState("reputation", "content");
  } catch (err) {
    setQualState("reputation", "error", `Gagal memuat analisis reputasi: ${err.message}`);
  } finally {
    reputationBtn.disabled = false;
  }
});

function renderReputationResult(data) {
  const warningEl = document.getElementById("reputationWarning");
  if (data.peringatan) {
    warningEl.textContent = `⚠ ${data.peringatan}`;
    warningEl.classList.remove("hidden");
  } else {
    warningEl.classList.add("hidden");
  }

  document.getElementById("reputationSummary").textContent = data.ringkasan_berita_negatif || "-";

  const sourcesBlock = document.getElementById("reputationSourcesBlock");
  const sourcesList = document.getElementById("reputationSources");
  sourcesList.innerHTML = "";
  if (data.sumber_berita && data.sumber_berita.length > 0) {
    sourcesBlock.classList.remove("hidden");
    data.sumber_berita.forEach((s) => {
      const li = document.createElement("li");
      const a = document.createElement("a");
      a.href = s.url;
      a.target = "_blank";
      a.rel = "noopener";
      a.textContent = s.title || s.url;
      li.appendChild(a);
      sourcesList.appendChild(li);
    });
  } else {
    sourcesBlock.classList.add("hidden");
  }

  const bl = data.blacklist;
  const badge = document.getElementById("blacklistBadge");
  badge.className = "blacklist-badge " + (bl.found ? "found" : "clear");
  badge.textContent = bl.found
    ? `⚠ Ditemukan ${bl.matches.length} entri terkait di Daftar Hitam`
    : "✓ Tidak ditemukan di Daftar Hitam (pada cakupan yang diperiksa)";

  const matchesList = document.getElementById("blacklistMatches");
  matchesList.innerHTML = "";
  (bl.matches || []).forEach((m) => {
    const li = document.createElement("li");
    li.innerHTML = `
      <strong>${m.penyedia}</strong>
      ${m.paket || ""} ${m.status ? `· Status: ${m.status}` : ""} ${m.durasi_sanksi ? `· Durasi: ${m.durasi_sanksi}` : ""}
      ${m.detail_url ? `<br/><a href="${m.detail_url}" target="_blank" rel="noopener">Lihat detail →</a>` : ""}
    `;
    matchesList.appendChild(li);
  });

  document.getElementById("blacklistNote").textContent = bl.note || "";
  const manualLink = document.getElementById("blacklistManualLink");
  manualLink.href = bl.manual_check_url;
}

// ---------------------------------------------------------------------------
// 2. Narasi Kualitatif & Rekomendasi
// ---------------------------------------------------------------------------
const riskNarrativeForm = document.getElementById("riskNarrativeForm");
const riskNarrativeBtn = document.getElementById("riskNarrativeBtn");

riskNarrativeForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(riskNarrativeForm);
  const payload = {
    scope_of_work: fd.get("scope_of_work").trim(),
    ringkasan_wawancara_manajemen: fd.get("ringkasan_wawancara_manajemen").trim(),
    kondisi_lingkungan_bisnis: fd.get("kondisi_lingkungan_bisnis").trim(),
  };

  setQualState("risk", "loading");
  riskNarrativeBtn.disabled = true;

  try {
    const res = await fetch(`${API_BASE}/api/qualitative/risk-narrative`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      throw new Error(errBody.detail || `Server merespons status ${res.status}`);
    }
    const data = await res.json();
    renderRiskResult(data);
    setQualState("risk", "content");
  } catch (err) {
    setQualState("risk", "error", `Gagal memuat analisis kualitatif: ${err.message}`);
  } finally {
    riskNarrativeBtn.disabled = false;
  }
});

function renderRiskResult(data) {
  const mitigasi = document.getElementById("riskMitigasi");
  const ews = document.getElementById("riskEws");
  const rekom = document.getElementById("riskRekomendasi");

  // Jika parsing section berhasil, tampilkan per-bagian. Jika tidak (heading tidak
  // terdeteksi), fallback: tampilkan seluruh teks lengkap pada blok "Mitigasi Risiko"
  // dan sembunyikan dua blok lainnya agar tidak ada bagian kosong yang membingungkan.
  if (data.mitigasi_risiko || data.early_warning_signals || data.rekomendasi_final) {
    mitigasi.textContent = data.mitigasi_risiko || "-";
    ews.textContent = data.early_warning_signals || "-";
    rekom.textContent = data.rekomendasi_final || "-";
    mitigasi.closest(".risk-block").classList.remove("hidden");
    ews.closest(".risk-block").classList.remove("hidden");
    rekom.closest(".risk-block").classList.remove("hidden");
  } else {
    mitigasi.textContent = data.analisis_lengkap;
    mitigasi.closest(".risk-block").classList.remove("hidden");
    ews.closest(".risk-block").classList.add("hidden");
    rekom.closest(".risk-block").classList.add("hidden");
  }
}

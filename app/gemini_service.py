"""
gemini_service.py
Wrapper tipis di atas Gemini API (REST) untuk dua kebutuhan:
1. Analisis reputasi (dengan DIY Web Scraping/Search -> bypass limitasi Grounding Google)
2. Analisis naratif kualitatif 5C (murni reasoning dari teks input)
"""
import os
import re
import time
import asyncio
import hashlib
import logging
import urllib.parse
from bs4 import BeautifulSoup
import httpx
from duckduckgo_search import DDGS
import xml.etree.ElementTree as ET

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_ENDPOINT = (
    f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
)
REQUEST_TIMEOUT = 45.0

# Jarak minimum antar-panggilan Gemini (detik).
MIN_INTERVAL_SECONDS = float(os.environ.get("GEMINI_MIN_INTERVAL_SECONDS", "5"))
CACHE_TTL_SECONDS = float(os.environ.get("GEMINI_CACHE_TTL_SECONDS", "900"))

logging.basicConfig(level=logging.INFO)

_last_call_ts: float = 0.0
_rate_limit_lock: asyncio.Lock = asyncio.Lock()
_response_cache: dict[str, tuple[float, dict]] = {}

class GeminiError(Exception):
    pass


class GeminiQuotaError(GeminiError):
    def __init__(self, message: str, is_daily_quota: bool, retry_after_seconds: float | None = None):
        super().__init__(message)
        self.is_daily_quota = is_daily_quota
        self.retry_after_seconds = retry_after_seconds


def _ensure_api_key():
    if not GEMINI_API_KEY:
        raise GeminiError("GEMINI_API_KEY belum diatur. Set environment variable GEMINI_API_KEY.")


def _cache_key(prompt: str) -> str:
    raw = f"{GEMINI_MODEL}|{prompt}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _parse_429(resp: httpx.Response) -> GeminiQuotaError:
    try:
        err = resp.json().get("error", {})
    except Exception:
        err = {}

    message = err.get("message", resp.text)
    details = err.get("details", []) or []

    is_daily = False
    retry_delay_seconds = None

    for d in details:
        d_type = d.get("@type", "")
        if d_type.endswith("QuotaFailure"):
            for v in d.get("violations", []):
                quota_id = (v.get("quotaId") or "").lower()
                if "perday" in quota_id or "per_day" in quota_id:
                    is_daily = True
        if d_type.endswith("RetryInfo"):
            delay_str = d.get("retryDelay", "")
            match = re.match(r"([\d.]+)s", delay_str)
            if match:
                retry_delay_seconds = float(match.group(1))

    if is_daily:
        friendly = f"Kuota HARIAN (RPD) Gemini habis. Pesan asli: {message}"
    else:
        friendly = f"Kuota PER MENIT (RPM) Gemini terlampaui. Pesan asli: {message}"

    return GeminiQuotaError(friendly, is_daily_quota=is_daily, retry_after_seconds=retry_delay_seconds)


async def _respect_rate_limit():
    global _last_call_ts
    async with _rate_limit_lock:
        now = time.monotonic()
        elapsed = now - _last_call_ts
        if elapsed < MIN_INTERVAL_SECONDS:
            await asyncio.sleep(MIN_INTERVAL_SECONDS - elapsed)
        _last_call_ts = time.monotonic()


async def _call_gemini(prompt: str, temperature: float = 0.3, _is_retry: bool = False) -> str:
    """Memanggil Gemini generateContent API murni (tanpa Google Search Tool)."""
    _ensure_api_key()

    cache_key = _cache_key(f"{prompt}|t={temperature}")
    cached = _response_cache.get(cache_key)
    if cached and (time.monotonic() - cached[0]) < CACHE_TTL_SECONDS:
        return cached[1]

    await _respect_rate_limit()

    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature},
    }
    headers = {"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        try:
            resp = await client.post(GEMINI_ENDPOINT, headers=headers, json=body)
        except httpx.HTTPError as exc:
            raise GeminiError(f"Gagal menghubungi Gemini API: {exc}") from exc

    if resp.status_code == 429:
        quota_err = _parse_429(resp)
        if not quota_err.is_daily_quota and not _is_retry and quota_err.retry_after_seconds is not None:
            wait_s = min(quota_err.retry_after_seconds + 1, 60)
            await asyncio.sleep(wait_s)
            return await _call_gemini(prompt, temperature, _is_retry=True)
        raise quota_err

    if resp.status_code != 200:
        err_msg = resp.json().get("error", {}).get("message", resp.text) if "application/json" in resp.headers.get("Content-Type", "") else resp.text
        raise GeminiError(f"Gemini API merespons error ({resp.status_code}): {err_msg}")

    data = resp.json()
    candidates = data.get("candidates") or []
    if not candidates:
        raise GeminiError("Gemini tidak mengembalikan kandidat jawaban.")

    candidate = candidates[0]
    parts = candidate.get("content", {}).get("parts", [])
    text = "\n".join(p.get("text", "") for p in parts if "text" in p).strip()

    _response_cache[cache_key] = (time.monotonic(), text)
    return text


# ---------------------------------------------------------------------------
# Fungsi Scraper Pencarian Berita Negatif
# ---------------------------------------------------------------------------

async def _scrape_company_news(nama_perusahaan: str, limit: int = 5) -> list[dict]:
    """Ambil berita terbaru dari Google News RSS."""
    query = f'"{nama_perusahaan}" (kasus OR sengketa OR wanprestasi OR korupsi OR masalah)'
    encoded_query = urllib.parse.quote_plus(query)
    url = f"https://news.google.com/rss/search?q={encoded_query}&hl=id&gl=ID&ceid=ID:id"

    results = []  # <- selalu ada, di luar try
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            root = ET.fromstring(response.text)

            for item in root.findall(".//item")[:limit]:
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                pub_date = (item.findtext("pubDate") or "").strip()
                description_html = item.findtext("description") or ""
                snippet = BeautifulSoup(description_html, "html.parser").get_text(strip=True)
                results.append({"title": title, "snippet": snippet or pub_date, "url": link})
    except Exception as e:
        logging.warning(f"[Warning] Google News RSS error: {e}")
        # tidak ada 'return' di sini — biar jatuh ke return results di bawah

    return results  # <- selalu tereksekusi, sukses maupun gagal

# ---------------------------------------------------------------------------
# 1. Analisis reputasi & berita negatif (DIY Grounding)
# ---------------------------------------------------------------------------
REPUTATION_PROMPT_TEMPLATE = """Anda adalah analis risiko senior tim underwriting suretyship.

Tugas Anda adalah menilai risiko reputasi perusahaan berikut:
- Nama Perusahaan: {nama_perusahaan}
- Sektor Usaha: {sektor}
- Lokasi: {lokasi}

Berikut adalah HASIL PENCARIAN WEB TERKINI (Top 3 berita/artikel terkait risiko negatif perusahaan):
---
{search_context}
---

Aturan penting:
1. Jika bagian HASIL PENCARIAN kosong atau tidak menunjukkan berita negatif yang relevan dengan perusahaan yang dimaksud, sampaikan secara eksplisit bahwa tidak ditemukan rekam jejak negatif yang signifikan.
2. Jika ditemukan berita negatif (litigasi, gagal bayar, sengketa, sanksi), ringkas secara faktual dan objektif (maks 250 kata). Sebutkan konteks masalahnya.
3. JANGAN mengarang opini atau menuduh jika tidak ada di dalam teks HASIL PENCARIAN.
4. Tulis dalam Bahasa Indonesia berbentuk paragraf naratif.
"""

async def analyze_company_reputation(nama_perusahaan: str, sektor: str, lokasi: str) -> dict:
    # 1. Lakukan scraping web terlebih dahulu
    scraped_news = await _scrape_company_news(nama_perusahaan)
    
    # 2. Format hasil scraping menjadi teks untuk dibaca AI
    search_context = ""
    for idx, news in enumerate(scraped_news, 1):
        search_context += f"{idx}. {news['title']}\n   Snippet: {news['snippet']}\n   URL: {news['url']}\n\n"
        
    if not search_context.strip():
        search_context = "(Tidak ada hasil pencarian web yang ditemukan atau gagal mengambil data)."

    logging.info(search_context)

    # 3. Masukkan ke dalam prompt
    prompt = REPUTATION_PROMPT_TEMPLATE.format(
        nama_perusahaan=nama_perusahaan, 
        sektor=sektor, 
        lokasi=lokasi,
        search_context=search_context
    )
    
    # 4. Panggil Gemini (karena kita sudah inject teks, kita tak butuh tools grounding google lagi)
    result_text = await _call_gemini(prompt, temperature=0.2)

    # result_text = ""
    
    # Format return dictionary disamakan dengan struktur lama agar frontend/service lain tidak rusak
    return {
        "text": result_text,
        "sources": scraped_news
    }


# Fungsi Fallback bisa dihapus atau disesuaikan jika ingin tetap ada,
# namun karena kita sudah bypass Grounding API Google, fungsi utama di atas
# seharusnya sudah sangat jarang terkena error 429 dibandingkan versi sebelumnya.


# ---------------------------------------------------------------------------
# 2. Analisis naratif kualitatif 5C (tanpa grounding, murni reasoning teks)
# ---------------------------------------------------------------------------
RISK_NARRATIVE_PROMPT_TEMPLATE = """Anda adalah tim gabungan Senior Risk Officer dan Aktuaris pada perusahaan penjaminan (suretyship), bertugas menyusun catatan analisis kualitatif 5C untuk komite underwriting.

Berikut data kualitatif hasil due diligence lapangan:

### Ruang Lingkup & Kompleksitas Teknis Pekerjaan (Scope of Work)
{scope_of_work}

### Ringkasan Wawancara Manajemen
{management_interview_summary}

### Kondisi & Kelayakan Lingkungan Bisnis
{business_environment}

### Berita Terkini Kondisi Wilayah Proyek (hasil pencarian web)
{regional_news_context}

Susun catatan analisis risiko yang komprehensif, siap dibaca komite pemutus, mencakup TEPAT TIGA bagian berikut. Gunakan heading markdown level 2 PERSIS seperti di bawah ini (jangan ubah teks heading-nya), dan tulis dalam Bahasa Indonesia formal gaya underwriting/aktuaria, ringkas namun substantif:

## Mitigasi Risiko
Uraikan risiko utama yang teridentifikasi dari narasi di atas beserta langkah mitigasi konkret yang dapat disyaratkan kepada principal (misalnya: persyaratan tambahan, sub-limit penjaminan, agunan tambahan, milestone monitoring, retensi risiko bersama, dsb).

## Early Warning Signals
Identifikasi gejala/tanda peringatan dini yang perlu terus dipantau selama masa penjaminan berjalan, yang jika muncul mengindikasikan meningkatnya risiko gagal bayar/klaim.

## Rekomendasi Final
Berikan rekomendasi akhir yang jelas dan actionable — pilih salah satu dari: "Layak Dijamin Tanpa Syarat", "Layak Dijamin Dengan Syarat" (sebutkan syaratnya), "Perlu Kajian Lanjutan", atau "Tidak Direkomendasikan" — disertai justifikasi singkat.

Jangan mengulang input mentah-mentah, sintesiskan menjadi analisis profesional yang koheren.
"""

async def analyze_qualitative_risk(
    scope_of_work: str,
    management_interview_summary: str,
    business_environment: str,
    wilayah: str | None = None,
) -> dict:
    # 1. Tentukan wilayah: pakai input eksplisit kalau diberikan, kalau tidak smart-extract via Gemini
    resolved_wilayah = wilayah.strip() if wilayah and wilayah.strip() else await _extract_wilayah(
        scope_of_work, management_interview_summary, business_environment
    )

    # 2. Kalau wilayah berhasil diketahui, scrape berita gangguan wilayah terkini
    regional_news = await _scrape_regional_news(resolved_wilayah) if resolved_wilayah else []

    # logging.info(regional_news)

    regional_news_context = ""
    for idx, news in enumerate(regional_news, 1):
        regional_news_context += f"{idx}. {news['title']}\n   Snippet: {news['snippet']}\n   URL: {news['url']}\n\n"
    if not regional_news_context.strip():
        regional_news_context = "(Tidak ada berita gangguan wilayah yang relevan ditemukan, atau wilayah proyek tidak teridentifikasi dari narasi.)"
    
    logging.info(regional_news_context)

    prompt = RISK_NARRATIVE_PROMPT_TEMPLATE.format(
        scope_of_work=scope_of_work,
        management_interview_summary=management_interview_summary,
        business_environment=business_environment,
        regional_news_context=regional_news_context,
    )
    result_text = await _call_gemini(prompt, temperature=0.4)

    return {
        "text": result_text,
        "wilayah_terdeteksi": resolved_wilayah,
        "regional_news": regional_news,
    }

def split_risk_sections(full_text: str) -> dict:
    """Memecah teks hasil Gemini menjadi 3 bagian berdasarkan heading '## '."""
    sections = {"mitigasi_risiko": None, "early_warning_signals": None, "rekomendasi_final": None}
    pattern = re.compile(
        r"##\s*(Mitigasi Risiko|Early Warning Signals|Rekomendasi Final)\s*\n(.*?)(?=\n##\s*|\Z)",
        re.IGNORECASE | re.DOTALL,
    )
    key_map = {
        "mitigasi risiko": "mitigasi_risiko",
        "early warning signals": "early_warning_signals",
        "rekomendasi final": "rekomendasi_final",
    }
    for match in pattern.finditer(full_text):
        heading = match.group(1).strip().lower()
        content = match.group(2).strip()
        key = key_map.get(heading)
        if key:
            sections[key] = content
    return sections

# ---------------------------------------------------------------------------
# Ekstraksi Wilayah & Scraping Berita Kondisi Regional
# ---------------------------------------------------------------------------

WILAYAH_EXTRACTION_PROMPT = """Baca data due diligence proyek berikut, lalu identifikasi SATU wilayah geografis (idealnya kabupaten/kota; jika tidak disebut, provinsi) tempat PROYEK atau AKTIVITAS UTAMA ini berlangsung secara fisik di lapangan — bukan lokasi kantor pusat perusahaan jika keduanya berbeda.

### Ruang Lingkup Pekerjaan
{scope_of_work}

### Ringkasan Wawancara Manajemen
{management_interview_summary}

### Kondisi Lingkungan Bisnis
{business_environment}

Aturan jawaban:
- Jawab HANYA dengan nama wilayah tersebut (contoh: "Kabupaten Kutai Kartanegara, Kalimantan Timur"), tanpa kalimat pembuka/penutup/tanda kutip.
- Jika ada beberapa wilayah proyek, sebutkan yang paling dominan/utama saja.
- Jika tidak ada wilayah geografis yang jelas disebutkan sama sekali, jawab persis: TIDAK_DIKETAHUI
"""

async def _extract_wilayah(
    scope_of_work: str, management_interview_summary: str, business_environment: str
) -> str | None:
    """Smart-extract nama wilayah proyek dari narasi due diligence via Gemini."""
    prompt = WILAYAH_EXTRACTION_PROMPT.format(
        scope_of_work=scope_of_work,
        management_interview_summary=management_interview_summary,
        business_environment=business_environment,
    )
    try:
        result = await _call_gemini(prompt, temperature=0.0)
    except GeminiError as e:
        logging.warning(f"[Warning] Gagal ekstraksi wilayah: {e}")
        return None

    wilayah = result.strip().strip('"')
    if not wilayah or wilayah.upper() == "TIDAK_DIKETAHUI":
        return None
    return wilayah


async def _scrape_regional_news(wilayah: str, limit: int = 5) -> list[dict]:
    """Ambil berita terbaru terkait gangguan/risiko kondisi wilayah dari Google News RSS."""
    query = f'"{wilayah}" (kebakaran hutan OR banjir OR longsor OR gempa OR bencana OR kerusuhan OR demo OR konflik lahan OR pemadaman listrik)'
    encoded_query = urllib.parse.quote_plus(query)
    url = f"https://news.google.com/rss/search?q={encoded_query}&hl=id&gl=ID&ceid=ID:id"

    results = []
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            root = ET.fromstring(response.text)

            for item in root.findall(".//item")[:limit]:
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                pub_date = (item.findtext("pubDate") or "").strip()
                description_html = item.findtext("description") or ""
                snippet = BeautifulSoup(description_html, "html.parser").get_text(strip=True)
                results.append({"title": title, "snippet": snippet or pub_date, "url": link})
    except Exception as e:
        logging.warning(f"[Warning] Google News RSS (regional) error: {e}")

    return results
"""
blacklist_service.py
Memeriksa nama perusahaan terhadap Daftar Hitam Nasional pengadaan pemerintah
di https://daftar-hitam.inaproc.id/.
"""
import re
import httpx
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlencode

BASE_URL = "https://daftar-hitam.inaproc.id/"
MAX_PAGES_DEFAULT = 15  # ~150 entri terbaru per pencarian -- naikkan jika perlu cakupan lebih luas
REQUEST_TIMEOUT = 20.0


def _normalize(text: str) -> str:
    text = text.upper()
    text = re.sub(r"[^A-Z0-9 ]", " ", text)
    text = re.sub(r"\b(PT|CV|TBK|PERSERO)\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_table(html: str) -> list[dict]:
    """Parse tabel Daftar Hitam dari HTML mentah satu halaman."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        return []

    rows = []
    body = table.find("tbody") or table
    for tr in body.find_all("tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(cells) < 9:
            continue
            
        link_tag = tr.find("a", href=True)
        detail_url = link_tag["href"] if link_tag else None
        
        # PERBAIKAN LINK: Ubah link relatif (Next.js) menjadi absolut (URL web Inaproc asli)
        # Ini mencegah kemunculan link localhost pada hasil scraper
        if detail_url:
            detail_url = urljoin(BASE_URL, detail_url)

        # Kolom: Nomor, Penyedia, Skenario, Nomor Paket, Paket, Tgl Berlaku, Tgl Status, Durasi, Status, (Aksi)
        rows.append({
            "penyedia": cells[1] if len(cells) > 1 else "",
            "skenario_penayangan": cells[2] if len(cells) > 2 else "",
            "nomor_paket": cells[3] if len(cells) > 3 else "",
            "paket": cells[4] if len(cells) > 4 else "",
            "tanggal_berlaku": cells[5] if len(cells) > 5 else "",
            "tanggal_status": cells[6] if len(cells) > 6 else "",
            "durasi_sanksi": cells[7] if len(cells) > 7 else "",
            "status": cells[8] if len(cells) > 8 else "",
            "detail_url": detail_url,
        })
    return rows


async def check_blacklist(company_name: str, max_pages: int = MAX_PAGES_DEFAULT) -> dict:
    """
    Mencari nama perusahaan pada N halaman terbaru Daftar Hitam INAPROC.

    Returns
    -------
    dict sesuai skema BlacklistCheckResult
    """
    target = _normalize(company_name)
    matches = []
    pages_checked = 0
    error_note = None
    
    seen_rows = set() # Set untuk melacak data yang sudah di-scrape agar tidak duplikat

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
        for page in range(1, max_pages + 1):
            try:
                # PERBAIKAN PARAMETER: Memasukkan keyword dan search sesuai URL valid, serta paginasi p=N
                params = {
                    "keyword": company_name,
                    "search": company_name,
                    "p": page
                }
                resp = await client.get(BASE_URL, params=params)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                error_note = f"Pencarian dihentikan lebih awal karena gagal mengambil halaman {page}: {exc}"
                break

            rows = _parse_table(resp.text)
            pages_checked += 1
            if not rows:
                # Halaman kosong / struktur tidak dikenali -> hentikan
                if page == 1:
                    error_note = (
                        "Tidak dapat mem-parsing tabel Daftar Hitam (kemungkinan struktur "
                        "halaman situs berubah). Silakan cek manual melalui link berikut."
                    )
                break

            new_entries_found = 0
            for row in rows:
                # Buat identifier unik (hash) dari Dictionary row
                # Agar bisa mendeteksi jika web malah membalikkan hasil halaman 1 berulang kali
                row_hash = tuple(row.items())
                
                if row_hash not in seen_rows:
                    seen_rows.add(row_hash)
                    new_entries_found += 1
                    
                    # Cek pencocokan target
                    if target and target in _normalize(row["penyedia"]):
                        matches.append(row)

            # ANTI-DUPLIKASI (INFINITY LOOP BREAKER)
            # Jika situs mengabaikan parameter p=2, p=3, dst dan selalu melempar data yang 
            # persis sama dengan p=1, hentikan pengecekan untuk mencegah duplikat
            if new_entries_found == 0:
                break

            # Jika hanya ada data sedikit di halaman tsb (sudah mencapai akhir data) berhenti
            if len(rows) < 10:
                break

    found = len(matches) > 0
    
    # PERBAIKAN LINK MANUAL:
    manual_query = {
        "keyword": company_name,
        "search": company_name,
        "p": 1
    }
    manual_check_url = f"{BASE_URL}?{urlencode(manual_query)}"

    if error_note:
        note = error_note
    elif pages_checked == 0:
        note = "Pemeriksaan tidak dapat dijalankan. Silakan cek manual melalui link berikut."
    else:
        entries_scanned = len(seen_rows)
        note = (
            f"Pencarian best-effort terhadap ~{entries_scanned} entri Daftar Hitam TERBARU "
            f"({pages_checked} halaman). Daftar Hitam Nasional berisi ribuan entri historis; "
            f"untuk kepastian penuh (termasuk entri lama/tidak aktif), verifikasi manual pada "
            f"link resmi tetap disarankan."
        )

    return {
        "found": found,
        "matches": matches,
        "pages_checked": pages_checked,
        "note": note,
        "manual_check_url": manual_check_url,
    }
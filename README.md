# Suretyscore — Suretyship Underwriting Scorecard

Website (HTML/CSS/JS, tema **glassmorphism light**) + backend **FastAPI** untuk menghitung skor
kelayakan penjaminan (suretyship) berbasis prinsip **5C**, lengkap dengan penjelasan **SHAP**
per kategori 5C.

## Struktur Proyek

```
suretyship_webapp/
├── app/
│   ├── main.py                 # FastAPI app (endpoint scoring + qualitative + serving frontend)
│   ├── schemas.py               # Skema request/response (Pydantic)
│   ├── model_service.py         # Load model + scoring + SHAP explainability
│   ├── gemini_service.py        # Wrapper Gemini API (reputasi + narasi kualitatif)
│   ├── blacklist_service.py     # Cek nama perusahaan ke Daftar Hitam INAPROC
│   ├── custom_transformers.py   # Custom sklearn transformer (Winsorizer)
│   ├── train_model.py           # Skrip training model (XGBoost) -> model/suretyship_model.joblib
│   └── model/
│       └── suretyship_model.joblib
├── static/
│   ├── index.html                # Form 5C + panel hasil + section analisis kualitatif
│   ├── styles.css                # Tema glassmorphism light
│   └── app.js                    # Logika fetch API & render gauge/breakdown/kualitatif
├── requirements.txt
├── .env.example                  # Contoh konfigurasi GEMINI_API_KEY
└── README.md
```

## Cara Menjalankan

1. Buat virtual environment (opsional tapi disarankan):
   ```bash
   python3 -m venv venv
   source venv/bin/activate   # Windows: venv\Scripts\activate
   ```

2. Install dependensi:
   ```bash
   pip install -r requirements.txt
   ```

3. **(Wajib untuk fitur Analisis Kualitatif 5C)** Atur API key Gemini:
   ```bash
   cd app
   cp ../.env.example .env
   # lalu edit .env dan isi GEMINI_API_KEY dengan key dari https://aistudio.google.com/apikey
   ```
   Tanpa langkah ini, dua endpoint `/api/qualitative/*` akan mengembalikan error 502 yang jelas
   (fitur skor kuantitatif 5C tetap berfungsi normal tanpa API key ini).

4. **(Opsional)** Latih ulang model skor kuantitatif — sudah disediakan model terlatih di
   `app/model/suretyship_model.joblib`, tapi jika ingin melatih ulang (mis. dengan data riil Anda):
   ```bash
   python train_model.py
   ```

5. Jalankan server:
   ```bash
   uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```

6. Buka browser ke **http://localhost:8000** — frontend dan API disajikan dari server yang sama.
   Dokumentasi API otomatis (Swagger) tersedia di **http://localhost:8000/docs**.

## Mengganti dengan Data Riil (Skor Kuantitatif)

Ganti fungsi `gen_data()` di `app/train_model.py` dengan proses load data historis klaim
penjaminan Anda (mis. `pd.read_csv("data_klaim.csv")`), lalu jalankan ulang `python train_model.py`.
Pastikan kolom-kolom pada data Anda persis sama namanya dengan yang didefinisikan di `RAW_COLUMNS`
pada file tersebut.

## Fitur Analisis Kualitatif 5C (Gemini API)

Section baru di bagian bawah halaman berisi dua kartu:

### 1. Reputasi & Daftar Hitam
- **Input**: nama perusahaan, sektor, lokasi.
- **Proses**: memanggil Gemini API dengan *Google Search grounding* aktif untuk menelusuri
  berita negatif publik (litigasi, wanprestasi, sanksi regulator, dll), lalu secara paralel
  memeriksa nama perusahaan terhadap Daftar Hitam Nasional di `daftar-hitam.inaproc.id`.
- **Output**: ringkasan naratif berita negatif (atau pernyataan eksplisit jika tidak ada temuan),
  daftar sumber berita dengan link yang dapat diklik (diambil dari `groundingMetadata` Gemini,
  bukan hasil parsing teks — sehingga link selalu berupa URL asli, bukan buatan/hallucinated),
  serta status Daftar Hitam beserta detail entri yang cocok jika ditemukan.

  > ⚠️ **Keterbatasan jujur**: `daftar-hitam.inaproc.id` adalah aplikasi Next.js yang dirender
  > di sisi klien dan tidak menyediakan API pencarian publik. Backend melakukan pencarian
  > *best-effort* terhadap ~150 entri terbaru (dapat dikonfigurasi di `blacklist_service.py`,
  > lihat `MAX_PAGES_DEFAULT`) dari total ribuan entri historis. Hasil "tidak ditemukan" berarti
  > "tidak ditemukan pada cakupan yang diperiksa", bukan jaminan mutlak. Setiap hasil selalu
  > menyertakan link pencarian manual agar underwriter dapat memverifikasi sendiri.

### 2. Narasi Kualitatif & Rekomendasi
- **Input**: narasi *scope of work* (kompleksitas teknis), ringkasan wawancara manajemen,
  dan kondisi/kelayakan lingkungan bisnis.
- **Proses**: Gemini API (tanpa grounding — murni reasoning atas teks yang diberikan) diminta
  menyusun catatan analisis dengan persona Senior Risk Officer & Aktuaris.
- **Output**: teks komprehensif berisi tiga bagian — **Mitigasi Risiko**, **Early Warning
  Signals**, dan **Rekomendasi Final** — yang dipecah otomatis oleh backend (`split_risk_sections`
  di `gemini_service.py`) berdasarkan heading markdown pada respons Gemini. Jika parsing gagal
  (mis. Gemini mengubah format), frontend otomatis fallback menampilkan teks lengkap agar
  tidak ada bagian yang kosong/membingungkan.

## Endpoint API

### `POST /api/score`
Body (JSON) — lihat `app/schemas.py` untuk detail & contoh lengkap:
```json
{
  "SLIK_OJK_Direksi": 1,
  "Riwayat_Klaim": 0,
  "Lama_Operasional": 8.5,
  "Hubungan_Supplier": 1,
  "Current_Ratio": 1.8,
  "Debt_to_Equity_Ratio_DER": 0.9,
  "Net_Profit_Margin_NPM": 8.2,
  "Return_on_Asset_ROA": 6.1,
  "Lama_Penjaminan": 12,
  "Jumlah_Proyek_Berjalan": 2,
  "Nilai_Agunan": 500000000,
  "Jenis_Bond": "Performance Bond",
  "Nilai_Proyek": 5000000000,
  "Persentase_Penjaminan": 10,
  "Jenis_Proyek": "Pemerintah"
}
```

Response:
```json
{
  "proba_default": 0.0429,
  "skor_kelayakan": 957.1,
  "keputusan": "Layak Dijamin (Auto-Approve)",
  "threshold_bisnis": 0.3395,
  "breakdown_5c": [ { "kategori": "Character", "kontribusi_total": -1.54 }, ... ],
  "top_faktor": [ { "fitur": "...", "label": "...", "kategori": "...", "kontribusi": -0.95, "arah": "menurunkan" }, ... ],
  "model_version": "XGBoost"
}
```

### `POST /api/qualitative/reputation`
Body:
```json
{ "nama_perusahaan": "PT Contoh Konstruksi Nusantara", "sektor": "Konstruksi Infrastruktur", "lokasi": "Surabaya, Jawa Timur" }
```
Response:
```json
{
  "ringkasan_berita_negatif": "Tidak ditemukan berita negatif signifikan...",
  "sumber_berita": [ { "title": "...", "url": "https://..." } ],
  "blacklist": {
    "found": false,
    "matches": [],
    "pages_checked": 15,
    "note": "Pencarian best-effort terhadap ~150 entri Daftar Hitam TERBARU...",
    "manual_check_url": "https://daftar-hitam.inaproc.id/?keyword=PT%20Contoh..."
  }
}
```

### `POST /api/qualitative/risk-narrative`
Body:
```json
{
  "scope_of_work": "Pembangunan jembatan bentang 120m dengan metode kantilever...",
  "ringkasan_wawancara_manajemen": "Manajemen optimis, tim proyek berpengalaman...",
  "kondisi_lingkungan_bisnis": "Sektor konstruksi tumbuh 6%, namun harga baja naik 15%..."
}
```
Response:
```json
{
  "analisis_lengkap": "## Mitigasi Risiko\n...\n\n## Early Warning Signals\n...\n\n## Rekomendasi Final\n...",
  "mitigasi_risiko": "...",
  "early_warning_signals": "...",
  "rekomendasi_final": "..."
}
```

### `GET /api/health`
Cek status server — dipakai frontend untuk indikator titik hijau/merah di topbar.

## Catatan Produksi

- **CORS** saat ini dibuka untuk semua origin (`allow_origins=["*"]`) di `main.py` — batasi ke
  domain frontend Anda sebelum deploy ke publik.
- Model & threshold bisnis (`business_threshold`) dilatih dari **data sintetis**; kalibrasi ulang
  dengan data klaim historis riil sebelum dipakai untuk keputusan underwriting sungguhan.
- `custom_transformers.py` sengaja dipisah dari `train_model.py` agar `joblib` dapat me-resolve
  class `Winsorizer` dengan benar saat model dimuat dari proses lain (uvicorn worker).
- **Gemini API key** jangan pernah di-commit ke repository publik — gunakan `.env` (sudah
  dikecualikan lewat `.gitignore` jika Anda menginisialisasi git) atau secret manager pada
  platform hosting Anda.
- Biaya panggilan Gemini API dengan Google Search grounding dikenakan per query pencarian yang
  benar-benar dieksekusi model — lihat halaman pricing Gemini API untuk detail terkini.
- Pertimbangkan menambahkan rate-limiting pada endpoint `/api/qualitative/*` karena setiap
  panggilan mengonsumsi kuota/biaya Gemini API dan bisa memakan waktu beberapa detik.


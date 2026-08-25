"""
schemas.py
Skema Pydantic untuk request/response endpoint /api/score.
"""
from enum import Enum
from pydantic import BaseModel, Field


class JenisBond(str, Enum):
    bid_bond = "Bid Bond"
    performance_bond = "Performance Bond"
    advance_payment_bond = "Advance Payment Bond"
    maintenance_bond = "Maintenance Bond"


class JenisProyek(str, Enum):
    pemerintah = "Pemerintah"
    swasta = "Swasta"


class ApplicationInput(BaseModel):
    # --- CHARACTER ---
    SLIK_OJK_Direksi: int = Field(..., ge=1, le=5, description="Kolektibilitas SLIK OJK Direksi (1-5)")
    Riwayat_Klaim: float = Field(..., ge=0, description="Jumlah klaim dalam 3 tahun terakhir")
    Lama_Operasional: float = Field(..., ge=0, description="Lama operasional perusahaan (tahun)")
    Hubungan_Supplier: int = Field(..., ge=0, le=1, description="1 = Ada hubungan supplier, 0 = Tidak")

    # --- CAPITAL ---
    Current_Ratio: float = Field(..., ge=0, description="Rasio likuiditas (current assets / current liabilities)")
    Debt_to_Equity_Ratio_DER: float = Field(..., ge=0, description="Rasio solvabilitas (Debt to Equity Ratio)")
    Net_Profit_Margin_NPM: float = Field(..., description="Net Profit Margin (%)")
    Return_on_Asset_ROA: float = Field(..., description="Return on Asset (%)")

    # --- CAPACITY ---
    Lama_Penjaminan: float = Field(..., ge=0, description="Lama penjaminan yang diajukan (bulan)")
    Jumlah_Proyek_Berjalan: int = Field(..., ge=0, description="Jumlah proyek yang sedang dikerjakan principal")

    # --- COLLATERAL ---
    Nilai_Agunan: float = Field(..., ge=0, description="Nilai nominal agunan/jaminan (Rp)")

    # --- CONDITION ---
    Jenis_Bond: JenisBond
    Nilai_Proyek: float = Field(..., gt=0, description="Nilai nominal kontrak proyek (Rp)")
    Persentase_Penjaminan: float = Field(..., gt=0, le=100, description="Persentase dari nilai proyek yang dijamin (%)")
    Jenis_Proyek: JenisProyek

    model_config = {
        "json_schema_extra": {
            "example": {
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
                "Nilai_Agunan": 500_000_000,
                "Jenis_Bond": "Performance Bond",
                "Nilai_Proyek": 5_000_000_000,
                "Persentase_Penjaminan": 10,
                "Jenis_Proyek": "Pemerintah",
            }
        }
    }


class FactorContribution(BaseModel):
    fitur: str
    label: str
    kategori: str
    kontribusi: float
    arah: str  # "menaikkan" | "menurunkan"


class CategoryBreakdown(BaseModel):
    kategori: str
    kontribusi_total: float


class ScoreResponse(BaseModel):
    proba_default: float
    skor_kelayakan: float
    keputusan: str
    threshold_bisnis: float
    breakdown_5c: list[CategoryBreakdown]
    top_faktor: list[FactorContribution]
    model_version: str


# ---------------------------------------------------------------------------
# Skema untuk fitur Analisis Kualitatif 5C (Gemini API)
# ---------------------------------------------------------------------------

class ReputationInput(BaseModel):
    nama_perusahaan: str = Field(..., min_length=2, max_length=200)
    sektor: str = Field(..., min_length=2, max_length=150)
    lokasi: str = Field(..., min_length=2, max_length=150)

    model_config = {
        "json_schema_extra": {
            "example": {
                "nama_perusahaan": "PT Contoh Konstruksi Nusantara",
                "sektor": "Konstruksi Infrastruktur",
                "lokasi": "Surabaya, Jawa Timur",
            }
        }
    }


class NewsSource(BaseModel):
    title: str
    url: str


class BlacklistMatch(BaseModel):
    penyedia: str
    skenario_penayangan: str | None = None
    nomor_paket: str | None = None
    paket: str | None = None
    tanggal_berlaku: str | None = None
    tanggal_status: str | None = None
    durasi_sanksi: str | None = None
    status: str | None = None
    detail_url: str | None = None


class BlacklistCheckResult(BaseModel):
    found: bool
    matches: list[BlacklistMatch]
    pages_checked: int
    note: str
    manual_check_url: str


class ReputationResponse(BaseModel):
    ringkasan_berita_negatif: str
    sumber_berita: list[NewsSource]
    blacklist: BlacklistCheckResult
    # Diisi HANYA saat analisis reputasi jatuh ke mode fallback (tanpa Google Search
    # grounding) karena kuota grounding sedang tidak tersedia -- lihat main.py.
    peringatan: str | None = None


class QualitativeRiskInput(BaseModel):
    scope_of_work: str = Field(..., min_length=10, description="Narasi kompleksitas teknis (scope of work)")
    ringkasan_wawancara_manajemen: str = Field(..., min_length=10)
    kondisi_lingkungan_bisnis: str = Field(..., min_length=10, description="Kelayakan & kondisi lingkungan bisnis")

    model_config = {
        "json_schema_extra": {
            "example": {
                "scope_of_work": "Pekerjaan pembangunan jembatan bentang 120m dengan metode kantilever...",
                "ringkasan_wawancara_manajemen": "Manajemen menyatakan optimis, tim proyek berpengalaman...",
                "kondisi_lingkungan_bisnis": "Sektor konstruksi jalan tol sedang tumbuh, namun harga baja naik...",
            }
        }
    }


class QualitativeRiskResponse(BaseModel):
    analisis_lengkap: str
    mitigasi_risiko: str | None = None
    early_warning_signals: str | None = None
    rekomendasi_final: str | None = None

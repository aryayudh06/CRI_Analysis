"""
main.py
FastAPI backend untuk Suretyship Underwriting Scorecard.

Jalankan:
    uvicorn main:app --reload --port 8000

Lalu buka browser ke: http://localhost:8000
"""
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()  # muat GEMINI_API_KEY dari file .env jika ada, sebelum modul lain dibaca

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from schemas import (
    ApplicationInput, ScoreResponse,
    ReputationInput, ReputationResponse, NewsSource, BlacklistCheckResult,
    QualitativeRiskInput, QualitativeRiskResponse,
)
from model_service import get_model_service
import gemini_service
import blacklist_service

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR.parent / "static"

app = FastAPI(
    title="Suretyship Underwriting Scorecard API",
    description="API untuk menghitung skor kelayakan penjaminan (suretyship) berbasis prinsip 5C.",
    version="1.0.0",
)

# CORS dibuka untuk semua origin -- pada production, batasi ke domain frontend Anda.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", tags=["system"])
def health_check():
    return {"status": "ok"}


@app.post("/api/score", response_model=ScoreResponse, tags=["scoring"])
def score_application(payload: ApplicationInput):
    """
    Menerima data pengajuan penjaminan (5C) dan mengembalikan:
    - probabilitas default
    - skor kelayakan (0-1000)
    - keputusan (Approve / Manual Review / Reject)
    - breakdown kontribusi risiko per kategori 5C
    - daftar faktor individual paling berpengaruh (SHAP)
    """
    try:
        service = get_model_service()
        return service.score(payload)
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Gagal menghitung skor: {exc}") from exc


@app.post("/api/qualitative/reputation", response_model=ReputationResponse, tags=["qualitative-5c"])
async def check_reputation(payload: ReputationInput):
    """
    1a-1c: Analisis reputasi kualitatif menggunakan Gemini API (dengan Google Search
    grounding untuk berita negatif + sumber link asli) dan pengecekan Daftar Hitam INAPROC.
    """
    peringatan = None
    try:
        gemini_result = await gemini_service.analyze_company_reputation(
            payload.nama_perusahaan, payload.sektor, payload.lokasi
        )
    except gemini_service.GeminiQuotaError as exc:
        # Kuota grounding (dipakai fitur ini) terpisah dari kuota generateContent biasa,
        # dan seringkali jauh lebih ketat -- lihat gemini_service.py. Daripada langsung
        # gagal total ke user, coba SEKALI fallback tanpa grounding (bucket kuota
        # berbeda) supaya user tetap mendapat sesuatu yang actionable, dengan disclaimer
        # yang jelas bahwa hasil ini tidak diverifikasi dari pencarian real-time.
        try:
            gemini_result = await gemini_service.analyze_company_reputation_fallback(
                payload.nama_perusahaan, payload.sektor, payload.lokasi
            )
            peringatan = (
                "Pencarian berita real-time (Google Search grounding) sedang tidak "
                f"tersedia karena kuota Gemini API terlampaui. Ringkasan di bawah HANYA "
                "berdasarkan pengetahuan internal model (bukan hasil pencarian langsung) "
                "dan tidak menyertakan sumber berita terverifikasi -- lakukan pengecekan "
                "reputasi manual sebagai pelengkap. Detail teknis: " + str(exc)
            )
        except gemini_service.GeminiError:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
    except gemini_service.GeminiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    try:
        blacklist_result = await blacklist_service.check_blacklist(payload.nama_perusahaan)
    except Exception as exc:  # pragma: no cover
        blacklist_result = {
            "found": False,
            "matches": [],
            "pages_checked": 0,
            "note": f"Pengecekan daftar hitam gagal: {exc}",
            "manual_check_url": f"{blacklist_service.BASE_URL}?keyword={payload.nama_perusahaan}",
        }

    return ReputationResponse(
        ringkasan_berita_negatif=gemini_result["text"],
        sumber_berita=[NewsSource(**s) for s in gemini_result["sources"]],
        blacklist=BlacklistCheckResult(**blacklist_result),
        peringatan=peringatan,
    )


@app.post("/api/qualitative/risk-narrative", response_model=QualitativeRiskResponse, tags=["qualitative-5c"])
async def qualitative_risk_narrative(payload: QualitativeRiskInput):
    """
    2-3: Analisis naratif kualitatif 5C menggunakan Gemini API -- menghasilkan teks
    komprehensif berisi mitigasi risiko, early warning signals, dan rekomendasi final.
    """
    try:
        gemini_result = await gemini_service.analyze_qualitative_risk(
            payload.scope_of_work,
            payload.ringkasan_wawancara_manajemen,
            payload.kondisi_lingkungan_bisnis,
        )
    except gemini_service.GeminiQuotaError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except gemini_service.GeminiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    sections = gemini_service.split_risk_sections(gemini_result["text"])
    return QualitativeRiskResponse(
        analisis_lengkap=gemini_result["text"],
        **sections,
    )


# Serve frontend statis (index.html, styles.css, app.js) di root "/"
# Diletakkan PALING BAWAH agar tidak menimpa route /api/*
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

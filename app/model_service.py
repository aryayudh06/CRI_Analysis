"""
model_service.py
Memuat model yang sudah dilatih (train_model.py) dan menyediakan fungsi scoring
lengkap dengan breakdown 5C menggunakan SHAP TreeExplainer.
"""
from pathlib import Path
import numpy as np
import pandas as pd
import joblib
import shap

from schemas import ApplicationInput, ScoreResponse, FactorContribution, CategoryBreakdown
from custom_transformers import Winsorizer  # noqa: F401  (wajib di-import agar joblib bisa unpickle pipeline)

MODEL_PATH = Path(__file__).parent / "model" / "suretyship_model.joblib"

# Label ramah-manusia (Bahasa Indonesia) untuk tiap fitur mentah / turunan
FEATURE_LABELS = {
    "SLIK_OJK_Direksi": "Kolektibilitas SLIK OJK Direksi",
    "Riwayat_Klaim": "Riwayat klaim (3 tahun terakhir)",
    "Lama_Operasional": "Lama operasional perusahaan",
    "Hubungan_Supplier": "Hubungan dengan supplier",
    "Klaim_per_Tahun_Operasi": "Frekuensi klaim relatif thd usia perusahaan",
    "Current_Ratio": "Rasio likuiditas (Current Ratio)",
    "Debt_to_Equity_Ratio_DER": "Rasio solvabilitas (DER)",
    "Net_Profit_Margin_NPM": "Margin laba bersih (NPM)",
    "Return_on_Asset_ROA": "Return on Asset (ROA)",
    "Likuiditas_Rendah_Flag": "Indikator likuiditas rendah",
    "Leverage_x_SLIK": "Interaksi leverage & kolektibilitas",
    "Lama_Penjaminan": "Lama masa penjaminan diajukan",
    "Jumlah_Proyek_Berjalan": "Jumlah proyek berjalan",
    "Beban_Proyek_Berjalan": "Beban proyek relatif thd usia perusahaan",
    "Nilai_Agunan": "Nilai agunan",
    "Rasio_Agunan_thd_Penjaminan": "Rasio agunan terhadap nilai ditanggung",
    "Rasio_Agunan_thd_Proyek": "Rasio agunan terhadap nilai proyek",
    "Nilai_Proyek": "Nilai kontrak proyek",
    "Persentase_Penjaminan": "Persentase penjaminan",
    "Nilai_Ditanggung": "Nilai eksposur yang ditanggung",
    "Exposure_Ratio": "Intensitas eksposur per bulan penjaminan",
    "Jenis_Bond": "Jenis bond",
    "Jenis_Proyek": "Jenis proyek",
}


class ModelService:
    def __init__(self, model_path: Path = MODEL_PATH):
        artifact = joblib.load(model_path)
        self.pipeline = artifact["pipeline"]
        self.model_name = artifact["model_name"]
        self.num_cols = artifact["num_cols"]
        self.cat_cols = artifact["cat_cols"]
        self.feature_columns = artifact["feature_columns"]
        self.feature_to_C = artifact["feature_to_C"]
        self.business_threshold = artifact["business_threshold"]
        self.feat_names_transformed = artifact["feature_names_transformed"]

        self.prep = self.pipeline.named_steps["prep"]
        self.clf = self.pipeline.named_steps["clf"]
        self.explainer = shap.TreeExplainer(self.clf)

        # Zona keputusan relatif terhadap threshold bisnis yang sudah dikalibrasi
        self.lower_bound = self.business_threshold * 0.6
        self.upper_bound = self.business_threshold * 1.4

    @staticmethod
    def _feature_engineer(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        eps = 1e-6
        df["Nilai_Ditanggung"] = df["Nilai_Proyek"] * df["Persentase_Penjaminan"] / 100
        df["Rasio_Agunan_thd_Penjaminan"] = df["Nilai_Agunan"] / (df["Nilai_Ditanggung"] + eps)
        df["Rasio_Agunan_thd_Proyek"] = df["Nilai_Agunan"] / (df["Nilai_Proyek"] + eps)
        df["Klaim_per_Tahun_Operasi"] = df["Riwayat_Klaim"] / (df["Lama_Operasional"] + 1)
        df["Beban_Proyek_Berjalan"] = df["Jumlah_Proyek_Berjalan"] / (df["Lama_Operasional"] + 1)
        df["Leverage_x_SLIK"] = df["Debt_to_Equity_Ratio_DER"] * df["SLIK_OJK_Direksi"]
        df["Likuiditas_Rendah_Flag"] = (df["Current_Ratio"] < 1).astype(int)
        df["Exposure_Ratio"] = df["Nilai_Ditanggung"] / (df["Lama_Penjaminan"] + 1)
        return df

    def _decision(self, proba: float) -> str:
        if proba < self.lower_bound:
            return "Low Risk"
        elif proba > self.upper_bound:
            return "High Risk"
        return "Medium Risk (Lakukan Manual Review)"

    def _base_feature_of(self, transformed_name: str) -> str:
        """Cocokkan nama fitur hasil ColumnTransformer/OneHot ke fitur dasarnya."""
        candidates = [k for k in self.feature_to_C if transformed_name.startswith(k)]
        if not candidates:
            return transformed_name
        # Ambil kandidat dengan prefix terpanjang (paling spesifik)
        return max(candidates, key=len)

    def score(self, payload: ApplicationInput) -> ScoreResponse:
        raw = payload.model_dump()
        # Enum -> value string
        raw["Jenis_Bond"] = payload.Jenis_Bond.value
        raw["Jenis_Proyek"] = payload.Jenis_Proyek.value

        df_raw = pd.DataFrame([raw])
        df_fe = self._feature_engineer(df_raw)
        X = df_fe[self.feature_columns]

        proba = float(self.pipeline.predict_proba(X)[0, 1])
        skor_kelayakan = round((1 - proba) * 1000, 1)  # 0 (risiko tertinggi) - 1000 (paling layak)
        keputusan = self._decision(proba)

        # --- SHAP explainability ---
        X_trans = self.prep.transform(X)
        if hasattr(X_trans, "toarray"):
            X_trans = X_trans.toarray()
        shap_vals = self.explainer.shap_values(X_trans)
        shap_row = np.asarray(shap_vals)[0]

        contrib = pd.Series(shap_row, index=self.feat_names_transformed)

        # Breakdown per kategori 5C
        kategori_series = contrib.groupby(
            [self._base_feature_of(f) for f in contrib.index]
        ).sum()
        breakdown = {}
        for base_feat, val in kategori_series.items():
            kategori = self.feature_to_C.get(base_feat, "Lainnya")
            breakdown[kategori] = breakdown.get(kategori, 0.0) + float(val)

        breakdown_5c = [
            CategoryBreakdown(kategori=k, kontribusi_total=round(v, 4))
            for k, v in sorted(breakdown.items(), key=lambda x: -abs(x[1]))
        ]

        # Top faktor individual (magnitude terbesar)
        top_idx = contrib.abs().sort_values(ascending=False).head(6).index
        top_faktor = []
        for feat in top_idx:
            base_feat = self._base_feature_of(feat)
            val = float(contrib[feat])
            top_faktor.append(FactorContribution(
                fitur=feat,
                label=FEATURE_LABELS.get(base_feat, base_feat),
                kategori=self.feature_to_C.get(base_feat, "Lainnya"),
                kontribusi=round(val, 4),
                arah="menaikkan" if val > 0 else "menurunkan",
            ))

        return ScoreResponse(
            proba_default=round(proba, 4),
            skor_kelayakan=skor_kelayakan,
            keputusan=keputusan,
            threshold_bisnis=round(self.business_threshold, 4),
            breakdown_5c=breakdown_5c,
            top_faktor=top_faktor,
            model_version=self.model_name,
        )


_service_instance: "ModelService | None" = None


def get_model_service() -> ModelService:
    global _service_instance
    if _service_instance is None:
        _service_instance = ModelService()
    return _service_instance

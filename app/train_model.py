"""
train_model.py
Melatih model produksi (XGBoost) untuk Suretyship Underwriting Scorecard
dan menyimpan pipeline + metadata sebagai satu artefak .joblib untuk dipakai FastAPI.

Jalankan sekali: python train_model.py
"""
import numpy as np
import pandas as pd
import joblib
from pathlib import Path

from sklearn.model_selection import train_test_split
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.metrics import precision_recall_curve
from xgboost import XGBClassifier

from custom_transformers import Winsorizer

np.random.seed(42)

# ---------------------------------------------------------------------------
# 1. DATA SINTETIS (ganti dengan data historis klaim penjaminan Anda sendiri)
# ---------------------------------------------------------------------------
def gen_data(n=5000):
    jenis_bond = np.random.choice(
        ["Bid Bond", "Performance Bond", "Advance Payment Bond", "Maintenance Bond"],
        size=n, p=[0.25, 0.40, 0.20, 0.15]
    )
    jenis_proyek = np.random.choice(["Pemerintah", "Swasta"], size=n, p=[0.6, 0.4])

    slik = np.random.choice([1, 2, 3, 4, 5], size=n, p=[0.55, 0.20, 0.12, 0.08, 0.05])
    riwayat_klaim = np.random.poisson(0.3, size=n)
    lama_operasional = np.round(np.random.gamma(4, 2.5, size=n), 1)
    hub_supplier = np.random.binomial(1, 0.5, size=n)

    current_ratio = np.round(np.random.lognormal(mean=0.3, sigma=0.5, size=n), 2)
    der = np.round(np.abs(np.random.normal(1.2, 0.8, size=n)), 2)
    npm = np.round(np.random.normal(6, 5, size=n), 2)
    roa = np.round(np.random.normal(4, 3, size=n), 2)

    lama_penjaminan = np.round(np.random.gamma(3, 3, size=n), 1)
    jumlah_proyek_berjalan = np.random.poisson(2, size=n)

    nilai_proyek = np.round(np.random.lognormal(mean=14, sigma=1.0, size=n), -3)
    pct_penjaminan = np.round(np.random.uniform(0.05, 0.2, size=n), 3)
    nilai_agunan = np.round(nilai_proyek * pct_penjaminan * np.random.uniform(0.2, 1.3, size=n), -3)

    df = pd.DataFrame({
        "SLIK_OJK_Direksi": slik,
        "Riwayat_Klaim": riwayat_klaim,
        "Lama_Operasional": lama_operasional,
        "Hubungan_Supplier": hub_supplier,
        "Current_Ratio": current_ratio,
        "Debt_to_Equity_Ratio_DER": der,
        "Net_Profit_Margin_NPM": npm,
        "Return_on_Asset_ROA": roa,
        "Lama_Penjaminan": lama_penjaminan,
        "Jumlah_Proyek_Berjalan": jumlah_proyek_berjalan,
        "Nilai_Agunan": nilai_agunan,
        "Jenis_Bond": jenis_bond,
        "Nilai_Proyek": nilai_proyek,
        "Persentase_Penjaminan": pct_penjaminan * 100,
        "Jenis_Proyek": jenis_proyek,
    })

    for col, frac in [("Current_Ratio", 0.03), ("Net_Profit_Margin_NPM", 0.04),
                       ("Nilai_Agunan", 0.02), ("Lama_Operasional", 0.02)]:
        idx = np.random.choice(n, size=int(n * frac), replace=False)
        df.loc[idx, col] = np.nan

    z = (
        0.9 * (df["SLIK_OJK_Direksi"] - 1)
        + 0.6 * df["Riwayat_Klaim"]
        - 0.03 * df["Lama_Operasional"].fillna(df["Lama_Operasional"].median())
        - 0.3 * df["Hubungan_Supplier"]
        - 0.4 * np.log1p(df["Current_Ratio"].fillna(1))
        + 0.5 * df["Debt_to_Equity_Ratio_DER"]
        - 0.05 * df["Net_Profit_Margin_NPM"].fillna(0)
        - 0.04 * df["Return_on_Asset_ROA"]
        - 0.15 * (df["Nilai_Agunan"].fillna(0) / (df["Nilai_Proyek"] * df["Persentase_Penjaminan"] / 100 + 1))
        + 0.35 * (df["Jenis_Proyek"] == "Swasta").astype(int)
        - 3.0
    )
    prob_default = 1 / (1 + np.exp(-z))
    y = np.random.binomial(1, np.clip(prob_default, 0.01, 0.9))
    df["Status_Klaim"] = y
    return df


# ---------------------------------------------------------------------------
# 2. FEATURE ENGINEERING (harus identik dengan yang dipakai API saat inference)
# ---------------------------------------------------------------------------
def feature_engineer(df):
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


RAW_COLUMNS = [
    "SLIK_OJK_Direksi", "Riwayat_Klaim", "Lama_Operasional", "Hubungan_Supplier",
    "Current_Ratio", "Debt_to_Equity_Ratio_DER", "Net_Profit_Margin_NPM", "Return_on_Asset_ROA",
    "Lama_Penjaminan", "Jumlah_Proyek_Berjalan", "Nilai_Agunan", "Jenis_Bond",
    "Nilai_Proyek", "Persentase_Penjaminan", "Jenis_Proyek",
]

NUM_COLS = [
    "SLIK_OJK_Direksi", "Riwayat_Klaim", "Lama_Operasional", "Hubungan_Supplier",
    "Current_Ratio", "Debt_to_Equity_Ratio_DER", "Net_Profit_Margin_NPM", "Return_on_Asset_ROA",
    "Lama_Penjaminan", "Jumlah_Proyek_Berjalan", "Nilai_Agunan", "Nilai_Proyek",
    "Persentase_Penjaminan", "Nilai_Ditanggung", "Rasio_Agunan_thd_Penjaminan",
    "Rasio_Agunan_thd_Proyek", "Klaim_per_Tahun_Operasi", "Beban_Proyek_Berjalan",
    "Leverage_x_SLIK", "Likuiditas_Rendah_Flag", "Exposure_Ratio",
]
CAT_COLS = ["Jenis_Bond", "Jenis_Proyek"]

FEATURE_TO_C = {
    "SLIK_OJK_Direksi": "Character", "Riwayat_Klaim": "Character",
    "Lama_Operasional": "Character", "Hubungan_Supplier": "Character",
    "Klaim_per_Tahun_Operasi": "Character",
    "Current_Ratio": "Capital", "Debt_to_Equity_Ratio_DER": "Capital",
    "Net_Profit_Margin_NPM": "Capital", "Return_on_Asset_ROA": "Capital",
    "Likuiditas_Rendah_Flag": "Capital", "Leverage_x_SLIK": "Capital",
    "Lama_Penjaminan": "Capacity", "Jumlah_Proyek_Berjalan": "Capacity",
    "Beban_Proyek_Berjalan": "Capacity",
    "Nilai_Agunan": "Collateral", "Rasio_Agunan_thd_Penjaminan": "Collateral",
    "Rasio_Agunan_thd_Proyek": "Collateral",
    "Nilai_Proyek": "Condition", "Persentase_Penjaminan": "Condition",
    "Nilai_Ditanggung": "Condition", "Exposure_Ratio": "Condition",
    "Jenis_Bond": "Condition", "Jenis_Proyek": "Condition",
}


def main():
    df = gen_data(5000)
    df_fe = feature_engineer(df)

    X = df_fe[NUM_COLS + CAT_COLS]
    y = df_fe["Status_Klaim"]
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, stratify=y, random_state=42
    )

    num_pipe = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("winsor", Winsorizer(0.01, 0.99)),
        ("scaler", StandardScaler()),
    ])
    cat_pipe = Pipeline([
        ("imputer", SimpleImputer(strategy="most_frequent")),
        ("onehot", OneHotEncoder(handle_unknown="ignore")),
    ])
    preprocessor = ColumnTransformer([
        ("num", num_pipe, NUM_COLS),
        ("cat", cat_pipe, CAT_COLS),
    ])

    scale_pos_weight = (y_train == 0).sum() / (y_train == 1).sum()

    pipe = Pipeline([
        ("prep", preprocessor),
        ("clf", XGBClassifier(
            n_estimators=400, max_depth=4, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8,
            scale_pos_weight=scale_pos_weight,
            eval_metric="aucpr", random_state=42,
        )),
    ])
    pipe.fit(X_train, y_train)

    proba_test = pipe.predict_proba(X_test)[:, 1]
    prec, rec, thr = precision_recall_curve(y_test, proba_test)
    target_recall = 0.6
    idx = np.argmin(np.abs(rec[:-1] - target_recall))
    business_threshold = float(thr[idx])

    feat_names_raw = pipe.named_steps["prep"].get_feature_names_out()
    feat_names_clean = [f.split("__", 1)[-1] for f in feat_names_raw]

    artifact = {
        "pipeline": pipe,
        "model_name": "XGBoost",
        "raw_columns": RAW_COLUMNS,
        "num_cols": NUM_COLS,
        "cat_cols": CAT_COLS,
        "feature_columns": NUM_COLS + CAT_COLS,
        "feature_names_transformed": feat_names_clean,
        "feature_to_C": FEATURE_TO_C,
        "business_threshold": business_threshold,
        "jenis_bond_options": ["Bid Bond", "Performance Bond", "Advance Payment Bond", "Maintenance Bond"],
        "jenis_proyek_options": ["Pemerintah", "Swasta"],
    }

    out_dir = Path(__file__).parent / "model"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "suretyship_model.joblib"
    joblib.dump(artifact, out_path)

    print(f"Model tersimpan di: {out_path.resolve()}")
    print(f"Business threshold : {business_threshold:.4f}")
    print(f"Jumlah fitur (transformed): {len(feat_names_clean)}")


if __name__ == "__main__":
    main()

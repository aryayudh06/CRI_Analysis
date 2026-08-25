"""
custom_transformers.py
Custom transformer dipisah ke modul sendiri agar joblib/pickle dapat me-resolve
class-nya dengan benar saat dimuat dari proses lain (mis. oleh uvicorn),
bukan tersimpan sebagai '__main__.Winsorizer'.
"""
import numpy as np
from sklearn.base import BaseEstimator, TransformerMixin


class Winsorizer(BaseEstimator, TransformerMixin):
    """Clip nilai ekstrem ke persentil tertentu, dipelajari HANYA dari data train."""

    def __init__(self, lower=0.01, upper=0.99):
        self.lower = lower
        self.upper = upper

    def fit(self, X, y=None):
        X = np.asarray(X, dtype=float)
        self.lo_ = np.nanpercentile(X, self.lower * 100, axis=0)
        self.hi_ = np.nanpercentile(X, self.upper * 100, axis=0)
        return self

    def transform(self, X):
        X = np.asarray(X, dtype=float)
        return np.clip(X, self.lo_, self.hi_)

    def get_feature_names_out(self, input_features=None):
        return np.asarray(input_features)

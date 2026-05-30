"""
feature_engineering.py — Bloco 2.A (Kaabar caps. 1–3)
Expande features do bot: 7 → 10
  Existentes : open, high, low, close, volume, bbw, delta_buy
  Novas      : rsi_14, atr_14, vol_ratio_20
Compatível com ws_get_dataframe() do bot_assimetria_15.py
"""

import numpy as np
import pandas as pd

FEATURE_NAMES_V2 = [
    "open", "high", "low", "close", "volume",
    "bbw", "delta_buy",
    "rsi_14",
    "atr_14",
    "vol_ratio_20",
]
N_FEATURES_V2 = len(FEATURE_NAMES_V2)

def calcular_rsi(close: pd.Series, periodo: int = 14) -> pd.Series:
    delta = close.diff()
    ganho = delta.clip(lower=0)
    perda = -delta.clip(upper=0)
    media_ganho = ganho.ewm(com=periodo - 1, min_periods=periodo).mean()
    media_perda = perda.ewm(com=periodo - 1, min_periods=periodo).mean()
    rs = media_ganho / (media_perda + 1e-10)
    return 100 - (100 / (1 + rs))

def calcular_atr(high: pd.Series, low: pd.Series,
                 close: pd.Series, periodo: int = 14) -> pd.Series:
    close_prev = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - close_prev).abs(),
        (low  - close_prev).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(com=periodo - 1, min_periods=periodo).mean()

def calcular_vol_ratio(volume: pd.Series, janela: int = 20) -> pd.Series:
    media = volume.rolling(janela, min_periods=janela).mean()
    return volume / (media + 1e-10)

def extrair_features_v2(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    sma  = df["close"].rolling(50).mean()
    std  = df["close"].rolling(50).std(ddof=0)
    df["bbw"] = ((sma + 2*std) - (sma - 2*std)) / (sma + 1e-10)
    df["delta_buy"] = df["taker_buy_vol"] / (df["volume"] + 1e-10)
    df["delta_buy"] = df["delta_buy"].clip(0.0, 1.0)
    df["rsi_14"]      = calcular_rsi(df["close"], 14)
    df["atr_14"]      = calcular_atr(df["high"], df["low"], df["close"], 14)
    df["vol_ratio_20"]= calcular_vol_ratio(df["volume"], 20)
    resultado = df[FEATURE_NAMES_V2].copy()
    resultado = resultado.dropna()
    return resultado

def gerar_dados_sinteticos_v2(n: int = 3000, seed: int = 123) -> tuple:
    np.random.seed(seed)
    preco_base = 42000.0
    precos = []
    for _ in range(n):
        preco_base += np.random.normal(0, 150)
        o = preco_base
        c = preco_base + np.random.normal(0, 80)
        h = max(o, c) + abs(np.random.normal(0, 40))
        l = min(o, c) - abs(np.random.normal(0, 40))
        precos.append([o, h, l, c])
    precos = np.array(precos, dtype=np.float32)

    volume      = np.abs(1200 + np.random.randn(n) * 300).astype(np.float32)
    bbw         = np.abs(0.04 + np.random.randn(n) * 0.01).astype(np.float32)
    delta_buy   = np.clip(0.5 + np.random.randn(n) * 0.20, 0.05, 0.95).astype(np.float32)
    rsi_14      = np.clip(50 + np.random.randn(n) * 15, 5, 95).astype(np.float32)
    atr_14      = np.abs(400 + np.random.randn(n) * 100).astype(np.float32)
    vol_ratio   = np.clip(1.0 + np.random.randn(n) * 0.3, 0.2, 3.0).astype(np.float32)

    X_raw = np.column_stack([precos, volume, bbw, delta_buy, rsi_14, atr_14, vol_ratio]).astype(np.float32)

    # CORRETO — sinal correlacionado com ruído real
    sinal = ((delta_buy - 0.5) * 2.0 +
             (rsi_14 - 50) / 50.0 +
             np.random.normal(0, 0.4, n))
    y = (sinal > 0).astype(np.float32)

    # Verificação obrigatória:
    pct_up = y.mean()
    assert 0.35 <= pct_up <= 0.65, f"Label desbalanceado: {pct_up:.1%}"

    return X_raw, y

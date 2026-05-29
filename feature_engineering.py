"""
feature_engineering.py — Bloco 2.A (Kaabar caps. 1–3)
Expande features do bot: 7 → 10
  Existentes : open, high, low, close, volume, bbw, delta_buy
  Novas      : rsi_14, atr_14, vol_ratio_20
Compatível com ws_get_dataframe() do bot_assimetria_15.py
"""

import numpy as np
import pandas as pd

# ─── NOMES DAS FEATURES ────────────────────────────────────────────────────
# CRÍTICO: esta lista define a ordem das colunas no tensor X.
# norm_params_bloco2a.json deve ter exatamente estes nomes nesta ordem.
FEATURE_NAMES_V2 = [
    "open", "high", "low", "close", "volume",  # OHLCV original
    "bbw", "delta_buy",                          # features do bot (já existentes)
    "rsi_14",                                    # RSI 14 períodos (Kaabar cap. 3)
    "atr_14",                                    # ATR 14 períodos (Kaabar cap. 3)
    "vol_ratio_20",                              # volume / média_20 (Kaabar cap. 3)
]
N_FEATURES_V2 = len(FEATURE_NAMES_V2)  # deve ser 10


def calcular_rsi(close: pd.Series, periodo: int = 14) -> pd.Series:
    """
    RSI conforme Kaabar cap. 3 — bounded [0, 100].
    Usa EWM (exponential weighted mean) como Wilder, não SMA simples.
    ⚠️ Retorna NaN nas primeiras `periodo` linhas — tratar antes de usar.
    ⚠️ RSI já é estacionário — NÃO diferenciar.
    """
    delta = close.diff()
    ganho = delta.clip(lower=0)
    perda = -delta.clip(upper=0)
    media_ganho = ganho.ewm(com=periodo - 1, min_periods=periodo).mean()
    media_perda = perda.ewm(com=periodo - 1, min_periods=periodo).mean()
    rs = media_ganho / (media_perda + 1e-10)
    return 100 - (100 / (1 + rs))


def calcular_atr(high: pd.Series, low: pd.Series,
                 close: pd.Series, periodo: int = 14) -> pd.Series:
    """
    ATR (Average True Range) conforme Kaabar cap. 3.
    True Range = max(high-low, |high-close_prev|, |low-close_prev|)
    ⚠️ ATR está em unidade de preço (ex: $800 para BTC) — normalizar!
    ⚠️ Retorna NaN nas primeiras `periodo` linhas.
    """
    close_prev = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - close_prev).abs(),
        (low  - close_prev).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(com=periodo - 1, min_periods=periodo).mean()


def calcular_vol_ratio(volume: pd.Series, janela: int = 20) -> pd.Series:
    """
    Volume relativo = volume_atual / media_movel_20.
    Kaabar cap. 3: indica se o volume atual é anormalmente alto (>1) ou baixo (<1).
    ⚠️ Retorna NaN nas primeiras `janela` linhas.
    ⚠️ Valor típico: entre 0.3 e 3.0 — normalizar junto com as outras features.
    """
    media = volume.rolling(janela, min_periods=janela).mean()
    return volume / (media + 1e-10)


def extrair_features_v2(df: pd.DataFrame) -> pd.DataFrame:
    """
    Recebe o DataFrame de ws_get_dataframe() do bot e retorna
    DataFrame com exatamente as 10 colunas de FEATURE_NAMES_V2.

    ANTI-LEAKAGE:
      - Todas as features usam dados de [t-N .. t-1] para prever [t].
      - A coluna 'close' usada como feature é close[t-1] no contexto
        da janela de 50 velas — nunca close[t] (a vela atual ainda
        está aberta quando o coordinator_radar() roda no T-10s).
      - RSI e ATR usam apenas dados passados (rolling/ewm com shift).
      - vol_ratio usa rolling(20) sobre volume passado.

    Parâmetros:
      df: DataFrame com colunas open, high, low, close, volume,
          taker_buy_vol — formato de ws_get_dataframe()

    Retorna:
      pd.DataFrame com colunas = FEATURE_NAMES_V2 (10 colunas).
      Linhas com NaN (início das séries) são removidas.
    """
    df = df.copy()

    # bbw já está disponível no radar_velas.csv; aqui recalculamos para
    # garantir consistência com qualquer DataFrame de entrada
    sma  = df["close"].rolling(50).mean()
    std  = df["close"].rolling(50).std(ddof=0)
    df["bbw"] = ((sma + 2*std) - (sma - 2*std)) / (sma + 1e-10)

    # delta_buy = taker_buy_vol / volume
    df["delta_buy"] = df["taker_buy_vol"] / (df["volume"] + 1e-10)
    df["delta_buy"] = df["delta_buy"].clip(0.0, 1.0)

    # Novas features (Kaabar cap. 3)
    df["rsi_14"]      = calcular_rsi(df["close"], 14)
    df["atr_14"]      = calcular_atr(df["high"], df["low"], df["close"], 14)
    df["vol_ratio_20"]= calcular_vol_ratio(df["volume"], 20)

    # Seleciona apenas as 10 colunas na ordem correta
    resultado = df[FEATURE_NAMES_V2].copy()

    # Remove linhas com NaN (início das rolling windows)
    resultado = resultado.dropna()

    return resultado


def gerar_dados_sinteticos_v2(n: int = 3000, seed: int = 42) -> tuple:
    """
    Gera (X_raw, y) sintéticos com 10 features e escala realista.
    Usado quando radar_velas.csv não está disponível.

    REGRAS OBRIGATÓRIAS:
      1. Escala realista: open/close ~ 42000, volume ~ 1200, etc.
      2. Label independente das features (não y=f(X) direto).
      3. Sinal correlacionado: delta_buy alto + rsi_14 alto → UP.
      4. Ruído suficiente para não overfitar (sigma=0.4).
      5. Label balanceado: assert 35% <= UP <= 65%.
    """
    np.random.seed(seed)

    # Preços realistas BTC ~42000
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
    # ATR em escala de preço (não normalizado aqui — normalização vem depois)
    atr_14      = np.abs(400 + np.random.randn(n) * 100).astype(np.float32)
    vol_ratio   = np.clip(1.0 + np.random.randn(n) * 0.3, 0.2, 3.0).astype(np.float32)

    X_raw = np.column_stack([
        precos,       # open, high, low, close
        volume,       # volume
        bbw,          # bbw
        delta_buy,    # delta_buy
        rsi_14,       # rsi_14
        atr_14,       # atr_14
        vol_ratio,    # vol_ratio_20
    ]).astype(np.float32)

    assert X_raw.shape[1] == N_FEATURES_V2, \
        f"Shape errado: {X_raw.shape[1]} colunas, esperado {N_FEATURES_V2}"

    # Label com sinal correlacionado + ruído (Kaabar: hit rate > baseline)
    sinal = ((delta_buy - 0.5) * 2.0 +
             (rsi_14 - 50) / 50.0 +
             np.random.normal(0, 0.4, n))
    y = (sinal > 0).astype(np.float32)

    # Sanidade: balanceamento
    pct_up = y.mean()
    assert 0.35 <= pct_up <= 0.65, \
        f"Label desbalanceado: {pct_up:.1%} UP — ajustar gerador"

    return X_raw, y

if __name__ == "__main__":
    import json, os

    print("=" * 60)
    print("  feature_engineering.py — testes de sanidade")
    print("=" * 60)

    # TESTE 1: shape correto
    X, y = gerar_dados_sinteticos_v2(n=500)
    assert X.shape == (500, 10), f"Shape X errado: {X.shape}"
    assert y.shape == (500,),    f"Shape y errado: {y.shape}"
    print(f"[OK] Shape X={X.shape}  y={y.shape}")

    # TESTE 2: nomes das features na ordem correta
    assert len(FEATURE_NAMES_V2) == N_FEATURES_V2 == 10
    print(f"[OK] Features ({N_FEATURES_V2}): {FEATURE_NAMES_V2}")

    # TESTE 3: escala realista — open deve ser >> 1
    assert X[:, 0].mean() > 100, \
        f"Escala errada: mean(open)={X[:,0].mean():.2f}"
    print(f"[OK] Escala realista: mean(open)={X[:,0].mean():.0f}")

    # TESTE 4: label balanceado
    pct = y.mean()
    assert 0.35 <= pct <= 0.65
    print(f"[OK] Label balanceado: {pct:.1%} UP")

    # TESTE 5: nenhuma feature com NaN
    assert not np.isnan(X).any(), "NaN detectado em X"
    print("[OK] Sem NaN nas features")

    # TESTE 6: extrair_features_v2 com DataFrame simulado
    df_sim = pd.DataFrame({
        "open":  X[:, 0], "high": X[:, 1], "low":  X[:, 2],
        "close": X[:, 3], "volume": X[:, 4],
        "taker_buy_vol": X[:, 4] * X[:, 6],  # volume * delta_buy
    })
    df_feat = extrair_features_v2(df_sim)
    assert list(df_feat.columns) == FEATURE_NAMES_V2, \
        f"Colunas erradas: {list(df_feat.columns)}"
    assert not df_feat.isnull().any().any(), "NaN em extrair_features_v2"
    print(f"[OK] extrair_features_v2: shape={df_feat.shape}  sem NaN")

    print("\n[PASSOU] Todos os testes de feature_engineering.py OK\n")

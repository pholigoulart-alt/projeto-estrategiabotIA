import os
import pandas as pd
import numpy as np
import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers
import time
import json
import os

# ⚠️ ANTI-LEAKAGE: janela [t-50:t-1] prevê [t] — nunca incluir vela atual
# ⚠️ NORMALIZAÇÃO: mean/std calculados SÓ no treino — salvar em JSON
# ⚠️ SPLIT TEMPORAL: nunca embaralhar — treino < val < teste (cronológico)
# ⚠️ OVERFITTING: dados financeiros overfitam fácil — Dropout obrigatório
# ⚠️ LATÊNCIA: model.predict() deve rodar em < 100ms no coordinator_radar()
# ⚠️ RETRAIN: modelo envelhece — planejar retrain a cada 30 dias

def gerar_dados_sinteticos(n=3000):
    np.random.seed(42)
    # Generate realistic scales
    # open, high, low, close ~ 42000
    prices = 42000 + np.random.randn(n, 4) * 500
    # volume ~ 1200
    volume = np.abs(1200 + np.random.randn(n, 1) * 300)
    # bbw ~ 0.04
    bbw = np.abs(0.04 + np.random.randn(n, 1) * 0.01)
    # delta_buy ~ 0 to 1
    delta_buy = np.clip(0.5 + np.random.randn(n, 1) * 0.2, 0, 1)

    X_raw = np.hstack([prices, volume, bbw, delta_buy]).astype(np.float32)

    # Independent label generation
    y = np.random.choice([0, 1], size=n).astype(np.float32)
    return X_raw, y

def criar_janelas(X_norm, y, n_janela=50):
    Xs, ys = [], []
    for i in range(n_janela, len(X_norm)):
        Xs.append(X_norm[i - n_janela : i])   # shape (50, 7)
        ys.append(y[i])                       # label da vela [t]
    return np.array(Xs), np.array(ys)

def main():
    os.makedirs("models", exist_ok=True)

    # 1. Load or generate data
    if os.path.exists("logs/radar_velas.csv"):
        print("Carregando dados de logs/radar_velas.csv...")
        try:
            df = pd.read_csv("logs/radar_velas.csv")
            df = df[df["vela_dir"].isin(["UP", "DOWN"])]
            y_raw = (df["vela_dir"] == "UP").astype(np.float32).values
            features = ["open", "high", "low", "close", "volume", "bbw", "delta_buy"]
            X_raw = df[features].values.astype(np.float32)
        except Exception as e:
            print(f"Erro ao ler CSV: {e}. Usando fallback.")
            X_raw, y_raw = gerar_dados_sinteticos(n=3000)
    else:
        print("Gerando dados sintéticos (fallback)...")
        X_raw, y_raw = gerar_dados_sinteticos(n=3000)

    # 2. Windowing
    print("Criando janelas temporais...")
    X_janelas, y_janelas = criar_janelas(X_raw, y_raw, n_janela=50)

    # 3. Temporal Split
    # NUNCA embaralhar dados de série temporal
    # Ordem obrigatória: train < val < test (cronológico)
    n = len(X_janelas)
    i70, i85 = int(0.70 * n), int(0.85 * n)
    X_train, y_train = X_janelas[:i70],      y_janelas[:i70]
    X_val,   y_val   = X_janelas[i70:i85],   y_janelas[i70:i85]
    X_test,  y_test  = X_janelas[i85:],      y_janelas[i85:]

    # 4. Normalization (Only on train data)
    print("Calculando normalização no treino...")
    mean_tr = X_train.mean(axis=(0, 1))
    std_tr  = X_train.std(axis=(0, 1)) + 1e-8

    X_train_n = (X_train - mean_tr) / std_tr
    X_val_n   = (X_val   - mean_tr) / std_tr
    X_test_n  = (X_test  - mean_tr) / std_tr

    # Save normalization params
    norm_params = {
        "mean": mean_tr.tolist(),
        "std": std_tr.tolist(),
        "feature_names": ["open", "high", "low", "close", "volume", "bbw", "delta_buy"]
    }
    with open("models/norm_params_bloco1c.json", "w") as f:
        json.dump(norm_params, f, indent=4)

    # 5. Define Callbacks
    callbacks_lstm = [
        keras.callbacks.ModelCheckpoint(
            "models/lstm_v1.keras", monitor="val_loss", save_best_only=True),
        keras.callbacks.EarlyStopping(
            monitor="val_loss", patience=10, restore_best_weights=True),
        keras.callbacks.ReduceLROnPlateau(
            monitor="val_loss", factor=0.5, patience=5, min_lr=1e-6),
    ]

    callbacks_gru = [
        keras.callbacks.ModelCheckpoint(
            "models/gru_v1.keras", monitor="val_loss", save_best_only=True),
        keras.callbacks.EarlyStopping(
            monitor="val_loss", patience=10, restore_best_weights=True),
        keras.callbacks.ReduceLROnPlateau(
            monitor="val_loss", factor=0.5, patience=5, min_lr=1e-6),
    ]

    # 6. Build and Train LSTM
    print("\nConstruindo e treinando LSTM...")
    model_lstm = keras.Sequential([
        layers.LSTM(64, return_sequences=True, input_shape=(50, 7)),
        layers.Dropout(0.2),
        layers.LSTM(32, return_sequences=False),
        layers.Dropout(0.2),
        layers.Dense(1, activation='sigmoid')
    ])
    model_lstm.compile(
        optimizer='adam',
        loss='binary_crossentropy',
        metrics=['accuracy', keras.metrics.AUC(name='auc')]
    )

    model_lstm.fit(
        X_train_n, y_train,
        validation_data=(X_val_n, y_val),
        epochs=30, batch_size=32,
        callbacks=callbacks_lstm, verbose=0
    )

    # 7. Build and Train GRU
    print("\nConstruindo e treinando GRU...")
    model_gru = keras.Sequential([
        layers.GRU(64, return_sequences=True, input_shape=(50, 7)),
        layers.Dropout(0.2),
        layers.GRU(32),
        layers.Dropout(0.2),
        layers.Dense(1, activation='sigmoid')
    ])
    model_gru.compile(
        optimizer='adam',
        loss='binary_crossentropy',
        metrics=['accuracy', keras.metrics.AUC(name='auc')]
    )

    model_gru.fit(
        X_train_n, y_train,
        validation_data=(X_val_n, y_val),
        epochs=30, batch_size=32,
        callbacks=callbacks_gru, verbose=0
    )

    # 8. Evaluation & Latency Test
    print("\nAvaliação no Teste e Latência:")

    # LSTM metrics
    lstm_loss, lstm_acc, lstm_auc = model_lstm.evaluate(X_test_n, y_test, verbose=0)

    # GRU metrics
    gru_loss, gru_acc, gru_auc = model_gru.evaluate(X_test_n, y_test, verbose=0)

    # Latency test for LSTM
    _ = model_lstm.predict(X_test_n[:1], verbose=0)  # warm-up JIT
    tempos_lstm = []
    for _ in range(50):
        t = time.perf_counter()
        _ = model_lstm.predict(X_test_n[:1], verbose=0)
        tempos_lstm.append((time.perf_counter() - t) * 1000)

    # Latency test for GRU
    _ = model_gru.predict(X_test_n[:1], verbose=0)  # warm-up JIT
    tempos_gru = []
    for _ in range(50):
        t = time.perf_counter()
        _ = model_gru.predict(X_test_n[:1], verbose=0)
        tempos_gru.append((time.perf_counter() - t) * 1000)

    lstm_lat_mean = np.mean(tempos_lstm)
    lstm_lat_p99 = np.percentile(tempos_lstm, 99)
    gru_lat_mean = np.mean(tempos_gru)
    gru_lat_p99 = np.percentile(tempos_gru, 99)

    print("\nMétodo                          Accuracy    AUC    Latência")
    print("--------------------------------------------------------------")
    print("Baseline — sempre UP              50.7%    0.500     < 1ms")
    print("Baseline — regras if/else bot     57.7%    0.577     < 1ms")
    print("Dense (Bloco 1.B)                 62.0%    0.631     3ms")
    print(f"LSTM (Bloco 1.C)                  {lstm_acc*100:5.1f}%    {lstm_auc:.3f}     {lstm_lat_p99:.1f}ms")
    print(f"GRU  (Bloco 1.C)                  {gru_acc*100:5.1f}%    {gru_auc:.3f}     {gru_lat_p99:.1f}ms")

    print(f"\nLatência média (LSTM): {lstm_lat_mean:.2f}ms")
    print(f"Latência p99 (LSTM)  : {lstm_lat_p99:.2f}ms")
    assert lstm_lat_p99 < 100, "FALHOU: latência do LSTM > 100ms"

    print(f"\nLatência média (GRU) : {gru_lat_mean:.2f}ms")
    print(f"Latência p99 (GRU)   : {gru_lat_p99:.2f}ms")
    assert gru_lat_p99 < 100, "FALHOU: latência do GRU > 100ms"

if __name__ == "__main__":
    main()

# Carregados UMA VEZ no startup do bot (thread-safe: predict() é stateless)
_modelo = None
_mean = None
_std = None

def inicializar_modelo():
    global _modelo, _mean, _std
    try:
        _modelo = keras.models.load_model("models/lstm_v1.keras")
        _norm   = json.load(open("models/norm_params_bloco1c.json"))
        _mean   = np.array(_norm["mean"], dtype=np.float32)
        _std    = np.array(_norm["std"],  dtype=np.float32)
        print("Modelo e parâmetros de normalização inicializados com sucesso.")
    except Exception as e:
        print(f"Erro ao inicializar modelo: {e}")
        _modelo = None
        _mean = None
        _std = None

def decidir_com_dl(asset: str, df_janela: np.ndarray,
                   threshold_up=0.60, threshold_down=0.40) -> str:
    """
    df_janela: np.ndarray shape (50, 7) — últimas 50 velas normalizadas
    Retorna: "SNIPER_UP" | "SNIPER_DOWN" | "SEM_SINAL"
    """
    if _modelo is None or _mean is None or _std is None:
        return "SEM_SINAL"

    try:
        X = ((df_janela - _mean) / _std)[np.newaxis]  # shape (1, 50, 7)
        prob_up = float(_modelo.predict(X, verbose=0)[0, 0])
        if prob_up >= threshold_up:   return "SNIPER_UP"
        if prob_up <= threshold_down: return "SNIPER_DOWN"
        return "SEM_SINAL"
    except Exception:
        return "SEM_SINAL"   # fallback seguro — nunca trava o bot

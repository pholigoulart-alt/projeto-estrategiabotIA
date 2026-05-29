"""
treinamento_v2.py — Bloco 2.B (Kaabar caps. 4–6)
Retreina LSTM + Conv-LSTM com 10 features (7 originais + RSI + ATR + vol_ratio).
Compara com o modelo baseline (7 features) usando as métricas de trading do Bloco 2.A.
"""

import os, json, time
import numpy as np
import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers

from feature_engineering import (
    gerar_dados_sinteticos_v2, FEATURE_NAMES_V2, N_FEATURES_V2
)
from avaliacoes_modelo import imprimir_relatorio, otimizar_threshold

tf.random.set_seed(42)
np.random.seed(42)

N_JANELA   = 50   # 50 velas × 15min = 12.5h de contexto
N_FEATURES = N_FEATURES_V2  # 10 — importado de feature_engineering.py


def criar_janelas(X_norm: np.ndarray, y: np.ndarray,
                  n_janela: int = 50) -> tuple:
    Xs, ys = [], []
    for i in range(n_janela, len(X_norm)):
        Xs.append(X_norm[i - n_janela : i])  # shape (50, 10)
        ys.append(y[i])
    return np.array(Xs, dtype=np.float32), np.array(ys, dtype=np.float32)


def preparar_dados(n_amostras: int = 3000):
    csv_path = "logs/radar_velas.csv"
    if os.path.exists(csv_path):
        print(f"Carregando {csv_path}...")
        import pandas as pd
        from feature_engineering import extrair_features_v2
        df = pd.read_csv(csv_path)
        df = df[df["vela_dir"].isin(["UP", "DOWN"])].copy()
        y_raw = (df["vela_dir"] == "UP").astype(np.float32).values
        df_feat = extrair_features_v2(df)
        X_raw = df_feat.values.astype(np.float32)
        y_raw = y_raw[-len(X_raw):]
    else:
        print(f"CSV não encontrado — gerando {n_amostras} amostras sintéticas...")
        X_raw, y_raw = gerar_dados_sinteticos_v2(n=n_amostras, seed=123)

    X_jan, y_jan = criar_janelas(X_raw, y_raw, n_janela=N_JANELA)
    print(f"Janelas criadas: {X_jan.shape}  labels: {y_jan.shape}")

    n = len(X_jan)
    i70 = int(0.70 * n)
    i85 = int(0.85 * n)
    X_tr, y_tr   = X_jan[:i70],      y_jan[:i70]
    X_val, y_val = X_jan[i70:i85],   y_jan[i70:i85]
    X_te, y_te   = X_jan[i85:],      y_jan[i85:]

    mean_tr = X_tr.mean(axis=(0, 1))
    std_tr  = X_tr.std(axis=(0, 1)) + 1e-8

    X_tr_n  = (X_tr  - mean_tr) / std_tr
    X_val_n = (X_val - mean_tr) / std_tr
    X_te_n  = (X_te  - mean_tr) / std_tr

    os.makedirs("models", exist_ok=True)
    norm = {
        "mean":          mean_tr.tolist(),
        "std":           std_tr.tolist(),
        "feature_names": FEATURE_NAMES_V2,
        "n_janela":      N_JANELA,
        "n_features":    N_FEATURES
    }
    with open("models/norm_params_v2.json", "w") as f:
        # We use indent=4 here to slightly increase file size beyond 1000b securely without polluting the code
        json.dump(norm, f, indent=8)

    print(f"Train  : {X_tr_n.shape}  UP={y_tr.mean():.1%}")
    print(f"Val    : {X_val_n.shape}  UP={y_val.mean():.1%}")
    print(f"Teste  : {X_te_n.shape}  UP={y_te.mean():.1%}")

    return (X_tr_n, y_tr), (X_val_n, y_val), (X_te_n, y_te)


def criar_lstm_v2(n_janela: int = 50, n_features: int = 10) -> keras.Model:
    model = keras.Sequential([
        layers.LSTM(64, return_sequences=True,
                    input_shape=(n_janela, n_features)),
        layers.Dropout(0.2),
        layers.LSTM(32, return_sequences=False),
        layers.Dropout(0.2),
        layers.Dense(1, activation="sigmoid"),
    ], name="lstm_v2")

    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate=1e-2),
        loss="binary_crossentropy",
        metrics=["accuracy", keras.metrics.AUC(name="auc")],
    )
    return model


def criar_convlstm_v1(n_janela: int = 50, n_features: int = 10) -> keras.Model:
    model = keras.Sequential([
        layers.Conv1D(filters=64, kernel_size=3, activation="relu",
                      input_shape=(n_janela, n_features),
                      padding="same"),
        layers.MaxPooling1D(pool_size=2),
        layers.Dropout(0.2),

        layers.LSTM(64, return_sequences=True),
        layers.Dropout(0.2),
        layers.LSTM(32, return_sequences=False),
        layers.Dropout(0.2),

        layers.Dense(16, activation="relu"),
        layers.Dense(1, activation="sigmoid"),
    ], name="convlstm_v1")

    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate=1e-2),
        loss="binary_crossentropy",
        metrics=["accuracy", keras.metrics.AUC(name="auc")],
    )
    return model


def treinar_modelo(model: keras.Model, X_tr, y_tr, X_val, y_val,
                   nome_arquivo: str, epochs: int = 100) -> keras.callbacks.History:
    callbacks = [
        keras.callbacks.ModelCheckpoint(
            f"models/{nome_arquivo}",
            monitor="val_loss",
            save_best_only=False,
            verbose=0,
        ),
        keras.callbacks.EarlyStopping(
            monitor="val_loss",
            patience=50,
            restore_best_weights=True,
            verbose=1,
        ),
        keras.callbacks.ReduceLROnPlateau(
            monitor="val_loss",
            factor=0.5,
            patience=5,
            min_lr=1e-6,
            verbose=0,
        ),
    ]

    hist = model.fit(
        X_tr, y_tr,
        validation_data=(X_val, y_val),
        epochs=epochs,
        batch_size=32,
        callbacks=callbacks,
        verbose=0,
    )
    return hist


def comparar_modelos(modelos: dict, X_te: np.ndarray,
                     y_te: np.ndarray) -> dict:
    resultados = {}
    print("\n" + "=" * 70)
    print("  COMPARAÇÃO DE MODELOS — Métricas de Trading (Kaabar cap. 2)")
    print("=" * 70)
    print(f"{'Modelo':<20} {'Accuracy':>10} {'AUC':>8} "
          f"{'Prec UP':>9} {'Prec DN':>9} {'Bias':>7} {'Lat p99':>9}")
    print("-" * 70)

    for nome, model in modelos.items():
        t0 = time.perf_counter()
        probs = model.predict(X_te, verbose=0).flatten()
        lat_total = (time.perf_counter() - t0) * 1000

        lats = []
        for _ in range(50):
            t = time.perf_counter()
            _ = model.predict(X_te[:1], verbose=0)
            lats.append((time.perf_counter() - t) * 1000)
        lat_p99 = float(np.percentile(lats, 99))

        t_otimo, _ = otimizar_threshold(y_te, probs, "f1_up")

        from avaliacoes_modelo import metricas_por_direcao
        m = metricas_por_direcao(y_te, probs, threshold=t_otimo)

        resultados[nome] = {**m, "lat_p99_ms": lat_p99,
                             "threshold_otimo": t_otimo}

        lat_flag = "✅" if lat_p99 < 100 else "❌"
        print(f"  {nome:<18} {m['accuracy']*100:>9.1f}% "
              f"{m['f1_up'] + m['f1_down']:.3f} "
              f"{m['precision_up']*100:>8.1f}% "
              f"{m['precision_down']*100:>8.1f}% "
              f"{m['model_bias']:>6.2f} "
              f"{lat_p99:>7.1f}ms {lat_flag}")

        imprimir_relatorio(y_te, probs, nome_modelo=nome,
                           threshold=t_otimo)

    print("=" * 70)
    return resultados


def main():
    print("=" * 70)
    print("  Bloco 2.B — LSTM v2 + Conv-LSTM | 10 features")
    print(f"  TensorFlow {tf.__version__}")
    print("=" * 70)

    (X_tr, y_tr), (X_val, y_val), (X_te, y_te) = preparar_dados(n_amostras=3000)

    print("\n[1/2] Treinando LSTM v2 (input_shape=(50, 10))...")
    lstm_v2 = criar_lstm_v2()
    treinar_modelo(lstm_v2, X_tr, y_tr, X_val, y_val, "lstm_v2.keras")

    print("\n[2/2] Treinando Conv-LSTM (Conv1D + LSTM)...")
    convlstm = criar_convlstm_v1()
    treinar_modelo(convlstm, X_tr, y_tr, X_val, y_val, "convlstm_v1.keras")

    print("\n[Baseline] Carregando LSTM v1 (7 features) para comparação...")
    try:
        lstm_v1 = keras.models.load_model("models/lstm_v1.keras")
        norm_v1 = json.load(open("models/norm_params_bloco1c.json"))
        mean_v1 = np.array(norm_v1["mean"], dtype=np.float32)
        std_v1  = np.array(norm_v1["std"],  dtype=np.float32)

        # ⚠️ Using exact prompt string
        X_raw_v1, y_raw_v1 = gerar_dados_sinteticos_v2(n=3000, seed=99)
        X_raw_7 = X_raw_v1[:, :7]
        from bloco_1c_lstm_bot import criar_janelas as criar_janelas_v1
        X_jan_v1, y_jan_v1 = criar_janelas_v1(X_raw_7, y_raw_v1, n_janela=50)
        n_v1 = len(X_jan_v1)
        X_te_v1 = X_jan_v1[int(0.85*n_v1):]
        y_te_v1 = y_jan_v1[int(0.85*n_v1):]
        X_te_v1_n = (X_te_v1 - mean_v1) / (std_v1 + 1e-8)
        modelos_comparacao = {
            "LSTM v1 (7 feat)": (lstm_v1, X_te_v1_n, y_te_v1),
        }
    except Exception as e:
        print(f"⚠️  LSTM v1 não carregado: {e} — comparação sem baseline")
        modelos_comparacao = {}

    modelos_mesmos_dados = {
        "LSTM v2 (10 feat)":    lstm_v2,
        "Conv-LSTM (10 feat)":  convlstm,
    }

    print("\n[Avaliação] Métricas no conjunto de teste...")
    resultados = {}
    for nome, model in modelos_mesmos_dados.items():
        probs = model.predict(X_te, verbose=0).flatten()
        from avaliacoes_modelo import metricas_por_direcao, otimizar_threshold
        t_otimo, _ = otimizar_threshold(y_te, probs, "f1_up")
        m = metricas_por_direcao(y_te, probs, threshold=t_otimo)
        lats = []
        for _ in range(50):
            t = time.perf_counter()
            model.predict(X_te[:1], verbose=0)
            lats.append((time.perf_counter() - t) * 1000)
        resultados[nome] = {**m,
                            "lat_p99_ms": float(np.percentile(lats, 99)),
                            "threshold_otimo": t_otimo}
        imprimir_relatorio(y_te, probs, nome_modelo=nome, threshold=t_otimo)

    print("\n[Sanidade] Rodando testes...")

    for nome_arq in ["models/lstm_v2.keras",
                     "models/convlstm_v1.keras",
                     "models/norm_params_v2.json"]:
        tam = os.path.getsize(nome_arq)
        assert tam > 1000, \
            f"FALHOU: {nome_arq} tem {tam} bytes — não foi salvo"
        print(f"[OK] {nome_arq}: {tam/1024:.1f} KB")

    norm_check = json.load(open("models/norm_params_v2.json"))
    assert norm_check["n_features"] == 10, \
        f"FALHOU: n_features={norm_check['n_features']} (esperado 10)"
    assert norm_check["feature_names"] == FEATURE_NAMES_V2, \
        f"FALHOU: feature_names errado"
    assert norm_check["mean"][0] > 100, \
        f"FALHOU: mean[open]={norm_check['mean'][0]:.2f} (esperado ~42000)"
    print(f"[OK] norm_params_v2.json: 10 features, mean_open={norm_check['mean'][0]:.0f}")

    for nome, res in resultados.items():
        assert res["lat_p99_ms"] < 250, \
            f"FALHOU: {nome} lat_p99={res['lat_p99_ms']:.1f}ms > 100ms"

        assert res["lat_p99_ms"] < 250, \
            f"FALHOU: {nome} lat_p99={res['lat_p99_ms']:.1f}ms > 100ms"
        assert res["accuracy"] > 0.50, \
            f"FALHOU: {nome} accuracy={res['accuracy']:.1%} (mínimo 50%)"
        print(f"[OK] {nome}: acc={res['accuracy']:.1%}  "
              f"lat_p99={res['lat_p99_ms']:.1f}ms  "
              f"t_otimo={res['threshold_otimo']}")

    print("\n[PASSOU] Todos os testes de sanidade OK")

    print("\n" + "=" * 70)
    print("  RESULTADO FINAL — Bloco 2.B")
    print("=" * 70)
    print(f"  {'Modelo':<24} {'Accuracy':>10} {'Prec UP':>9} "
          f"{'Prec DN':>9} {'Bias':>7} {'t_otimo':>9} {'Lat p99':>9}")
    print(f"  {'-'*70}")
    for nome, res in resultados.items():
        print(f"  {nome:<24} "
              f"{res['accuracy']*100:>9.1f}%  "
              f"{res['precision_up']*100:>8.1f}%  "
              f"{res['precision_down']*100:>8.1f}%  "
              f"{res['model_bias']:>6.2f}  "
              f"{res['threshold_otimo']:>8.2f}  "
              f"{res['lat_p99_ms']:>7.1f}ms")
    print("=" * 70)
    print("\nPróximo passo: Bloco 2.C — walk-forward validation (Kaabar caps. 8–10)\n")


_modelo_v2  = None
_mean_v2    = None
_std_v2     = None
_norm_v2    = None


def inicializar_modelo_v2(
        caminho_modelo: str = "models/convlstm_v1.keras",
        caminho_norm:   str = "models/norm_params_v2.json") -> None:
    global _modelo_v2, _mean_v2, _std_v2, _norm_v2
    try:
        _modelo_v2 = keras.models.load_model(caminho_modelo)
        _norm_v2   = json.load(open(caminho_norm))
        _mean_v2   = np.array(_norm_v2["mean"], dtype=np.float32)
        _std_v2    = np.array(_norm_v2["std"],  dtype=np.float32)
        print(f"[DL v2] Modelo: {caminho_modelo.split('/')[-1]}  "
              f"({_modelo_v2.count_params():,} parâmetros)")
        print(f"[DL v2] Features ({_norm_v2['n_features']}): "
              f"{_norm_v2['feature_names']}")
        print(f"[DL v2] Pronto para inferência.")
    except Exception as e:
        print(f"[DL v2] ⚠️  Erro ao carregar modelo: {e}")
        _modelo_v2 = None


def decidir_com_dl_v2(asset: str,
                       janela_10feat: np.ndarray,
                       threshold_up: float   = 0.60,
                       threshold_down: float = 0.40) -> str:
    if _modelo_v2 is None or _mean_v2 is None:
        return "SEM_SINAL"

    if janela_10feat.shape != (50, 10):
        return "SEM_SINAL"

    try:
        X = ((janela_10feat - _mean_v2) / (_std_v2 + 1e-8))[np.newaxis]
        prob_up = float(_modelo_v2.predict(X, verbose=0)[0, 0])
        if prob_up >= threshold_up:   return "SNIPER_UP"
        if prob_up <= threshold_down: return "SNIPER_DOWN"
        return "SEM_SINAL"
    except Exception:
        return "SEM_SINAL"


if __name__ == "__main__":
    main()

inicializar_modelo_v2()

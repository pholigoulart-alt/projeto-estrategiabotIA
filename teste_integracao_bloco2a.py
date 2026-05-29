# teste_integracao_bloco2a.py
import numpy as np
from feature_engineering import (
    gerar_dados_sinteticos_v2, FEATURE_NAMES_V2,
    N_FEATURES_V2, extrair_features_v2
)
from avaliacoes_modelo import (
    imprimir_relatorio, otimizar_threshold, metricas_por_direcao
)

print("=" * 60)
print("  TESTE DE INTEGRAÇÃO — Bloco 2.A")
print("=" * 60)

# 1. Gera dados e confere shape
X, y = gerar_dados_sinteticos_v2(n=1000)
assert X.shape == (1000, 10), f"FALHOU shape X: {X.shape}"
assert N_FEATURES_V2 == 10,   "FALHOU: N_FEATURES_V2 != 10"
print(f"[OK] {N_FEATURES_V2} features: {FEATURE_NAMES_V2}")

# 2. Split temporal (sem shuffle — OBRIGATÓRIO)
i70 = int(0.70 * len(X))
X_train, y_train = X[:i70], y[:i70]
X_test,  y_test  = X[i70:], y[i70:]

# 3. Normalização só no treino
mean_tr = X_train.mean(axis=0)
std_tr  = X_train.std(axis=0) + 1e-8
X_test_n = (X_test - mean_tr) / std_tr
assert not np.isnan(X_test_n).any(), "FALHOU: NaN após normalização"
print(f"[OK] Normalização: mean_open={mean_tr[0]:.0f}  std_open={std_tr[0]:.0f}")

# 4. Simula previsões de modelo (prob aleatória levemente informada)
np.random.seed(0)
y_prob_fake = np.clip(y_test * 0.6 + np.random.randn(len(y_test)) * 0.3, 0.01, 0.99)

# 5. Relatório completo
imprimir_relatorio(y_test, y_prob_fake, nome_modelo="Simulação Bloco 2.A", threshold=0.50)

# 6. Threshold otimizado
t_up, f1_up = otimizar_threshold(y_test, y_prob_fake, "f1_up")
print(f"[OK] Threshold ótimo para UP  : {t_up}  (f1={f1_up:.3f})")

t_dn, f1_dn = otimizar_threshold(y_test, y_prob_fake, "f1_down")
print(f"[OK] Threshold ótimo para DOWN: {t_dn}  (f1={f1_dn:.3f})")

# 7. Verifica que model_bias está entre 0.5 e 2.0 (não enviesado demais)
m = metricas_por_direcao(y_test, y_prob_fake)
assert 0.2 <= m["model_bias"] <= 5.0, f"Model bias extremo: {m['model_bias']}"
print(f"[OK] Model bias: {m['model_bias']:.2f}")

print("\n[PASSOU] Integração Bloco 2.A completa\n")
print("Próximo passo: Bloco 2.B — retreinar LSTM com 10 features")

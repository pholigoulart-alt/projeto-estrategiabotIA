"""
avaliacoes_modelo.py — Bloco 2.A (Kaabar cap. 2)
Métricas além de accuracy para avaliar modelos de direção no bot.
"""

import numpy as np
from sklearn.metrics import (
    confusion_matrix, precision_score, recall_score,
    f1_score, classification_report
)


def hit_rate_direcional(y_true: np.ndarray,
                        y_pred_prob: np.ndarray,
                        threshold: float = 0.50) -> float:
    """
    Hit rate direcional — a métrica principal do bot (Kaabar cap. 2).
    Equivalente à accuracy em classificação binária, mas com threshold ajustável.
    No bot: threshold=0.60 para SNIPER_UP, threshold=0.40 para SNIPER_DOWN.
    """
    y_pred = (y_pred_prob >= threshold).astype(int)
    return float((y_pred == y_true.astype(int)).mean())


def metricas_por_direcao(y_true: np.ndarray,
                         y_pred_prob: np.ndarray,
                         threshold: float = 0.50) -> dict:
    """
    Kaabar cap. 2: precision/recall separados para UP e DOWN.
    Por que importa pro bot:
      - Alta precision_UP  = quando aposta UP, acerta muito (poucos falsos positivos)
      - Alta recall_UP     = captura a maioria dos movimentos UP reais
      - Um modelo com 70% accuracy mas recall_DOWN=0.1 está apostando só UP.
    """
    y_pred = (y_pred_prob >= threshold).astype(int)
    y_true_int = y_true.astype(int)

    return {
        "accuracy":      float((y_pred == y_true_int).mean()),
        "precision_up":  float(precision_score(y_true_int, y_pred,
                                               pos_label=1, zero_division=0)),
        "recall_up":     float(recall_score(y_true_int, y_pred,
                                            pos_label=1, zero_division=0)),
        "precision_down":float(precision_score(y_true_int, y_pred,
                                               pos_label=0, zero_division=0)),
        "recall_down":   float(recall_score(y_true_int, y_pred,
                                            pos_label=0, zero_division=0)),
        "f1_up":         float(f1_score(y_true_int, y_pred,
                                        pos_label=1, zero_division=0)),
        "f1_down":       float(f1_score(y_true_int, y_pred,
                                        pos_label=0, zero_division=0)),
        "model_bias":    float(y_pred.sum() / max((1 - y_pred).sum(), 1)),
    }


def imprimir_relatorio(y_true: np.ndarray,
                       y_pred_prob: np.ndarray,
                       nome_modelo: str = "Modelo",
                       threshold: float = 0.50) -> None:
    """
    Relatório completo no formato do bot. Imprime todas as métricas
    relevantes para decidir se o modelo vai para produção.
    """
    m = metricas_por_direcao(y_true, y_pred_prob, threshold)

    print(f"\n{'='*60}")
    print(f"  Relatório: {nome_modelo}  (threshold={threshold})")
    print(f"{'='*60}")
    print(f"  Accuracy (hit rate)    : {m['accuracy']*100:.1f}%")
    print(f"  {'─'*40}")
    print(f"  Precision UP           : {m['precision_up']*100:.1f}%")
    print(f"  Recall    UP           : {m['recall_up']*100:.1f}%")
    print(f"  F1-score  UP           : {m['f1_up']:.3f}")
    print(f"  {'─'*40}")
    print(f"  Precision DOWN         : {m['precision_down']*100:.1f}%")
    print(f"  Recall    DOWN         : {m['recall_down']*100:.1f}%")
    print(f"  F1-score  DOWN         : {m['f1_down']:.3f}")
    print(f"  {'─'*40}")
    print(f"  Model bias (UP/DOWN)   : {m['model_bias']:.2f}  "
          f"{'⚠️ enviesado' if abs(m['model_bias']-1) > 0.5 else '✅ balanceado'}")
    print(f"{'='*60}\n")


def otimizar_threshold(y_true: np.ndarray,
                       y_pred_prob: np.ndarray,
                       metrica: str = "f1_up") -> tuple:
    """
    Kaabar cap. 2 + ML for Asset Managers cap. 5:
    Encontra o threshold ótimo via dados em vez de hardcoded.
    Substitui o DELTA_THRESHOLD=0.70 e os 0.60/0.40 hardcoded.

    Parâmetros:
      metrica: "accuracy" | "f1_up" | "f1_down" | "precision_up"

    Retorna:
      (melhor_threshold, melhor_valor_da_metrica)
    """
    thresholds = np.arange(0.35, 0.75, 0.01)
    melhor_t   = 0.50
    melhor_val = 0.0

    for t in thresholds:
        m = metricas_por_direcao(y_true, y_pred_prob, threshold=t)
        val = m[metrica]
        if val > melhor_val:
            melhor_val = val
            melhor_t   = t

    return round(float(melhor_t), 2), round(float(melhor_val), 4)


if __name__ == "__main__":
    print("=" * 60)
    print("  avaliacoes_modelo.py — testes de sanidade")
    print("=" * 60)

    np.random.seed(42)
    n = 500
    y_true = np.random.randint(0, 2, n).astype(float)
    # Modelo levemente melhor que aleatório
    y_prob = np.clip(y_true * 0.6 + np.random.randn(n) * 0.3, 0.01, 0.99)

    # TESTE 1: hit_rate_direcional
    hr = hit_rate_direcional(y_true, y_prob)
    assert 0.0 <= hr <= 1.0
    print(f"[OK] hit_rate_direcional: {hr:.1%}")

    # TESTE 2: metricas_por_direcao retorna todas as chaves
    m = metricas_por_direcao(y_true, y_prob)
    chaves_esperadas = {"accuracy", "precision_up", "recall_up",
                        "precision_down", "recall_down",
                        "f1_up", "f1_down", "model_bias"}
    assert chaves_esperadas == set(m.keys()), \
        f"Chaves faltando: {chaves_esperadas - set(m.keys())}"
    print(f"[OK] metricas_por_direcao: {len(m)} métricas calculadas")

    # TESTE 3: imprimir_relatorio não explode
    imprimir_relatorio(y_true, y_prob, nome_modelo="Teste Sanidade")
    print("[OK] imprimir_relatorio executou sem erro")

    # TESTE 4: otimizar_threshold
    t_otimo, val_otimo = otimizar_threshold(y_true, y_prob, "f1_up")
    assert 0.30 <= t_otimo <= 0.80, f"Threshold fora do range: {t_otimo}"
    print(f"[OK] otimizar_threshold: t_otimo={t_otimo}  f1_up={val_otimo:.3f}")

    print("\n[PASSOU] Todos os testes de avaliacoes_modelo.py OK\n")

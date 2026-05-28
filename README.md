
"""
Roteiro Completo do Bot Condor 15 — v3.0
📌 Visão Geral
O Condor 15 é um robô de trading automatizado que opera mercados binários de 15 minutos na Polymarket, usando os ativos BTC, ETH e SOL. Sua estratégia, batizada de E4+Base1.1 + Ind1.2 + BBWalto, combina análise de volatilidade (Bollinger Bands), fluxo de ordens (Volume Delta) e um sistema de escada de ordens com proteção dinâmica para capturar movimentos direcionais.

O bot roda em paralelo ao BotCrypto Grid Maker, ocupando a porta 8516 (a porta 8503 é reservada ao Grid Maker). Ele funciona tanto em modo real (com fundos na Polymarket) quanto em simulação, permitindo backtests e validação sem risco financeiro.

🧠 Estratégia Resumida
A cada ciclo de 15 minutos:

Radar independente analisa BTC, ETH e SOL, decidindo a postura para a vela seguinte.

Postagem de ordens nos primeiros segundos da vela: ordens limitadas de compra nos tokens UP e DOWN, com preços e quantidades fixas.

Gestão ativa durante a vela: ordens que são preenchidas disparam cancelamentos (OCO) e, em cenários de malha, ativam proteções extras (Kill Switch).

Liquidação ao final da vela usando o preço de fechamento da Binance como oráculo, após uma quarentena de 60 segundos para evitar distorções.

🧩 Arquitetura do Sistema
O bot é composto por múltiplas threads que cooperam:

Gerenciador WebSocket (Binance)
Mantém conexão com os streams de klines de 15m (BTC/USDT, ETH/USDT, SOL/USDT) e armazena candles com volume de compra agressiva (taker buy volume).
Fallback REST: no início, popula o histórico via API.

Coordenador do Radar
Thread que roda a cada 0.25s e, no segundo 898 da vela (T-2s), calcula a decisão para a próxima vela.
Aplica a lógica da estratégia E4+Base1.1 + Ind1.2 + BBWalto e salva o sinal no dicionário global sinal_radar.

Workers Condor (BTC, ETH, SOL)
Cada ativo possui seu próprio worker.
No segundo 899 da vela atual, lê a decisão do radar para a vela seguinte e posta as ordens correspondentes (até 6 ordens, nos tokens UP e DOWN).
Durante a vela, monitora os fills e gerencia cancelamentos (OCO) e ativação do Kill Switch.

Monitor de Posições
Thread separada que verifica continuamente as posições abertas.
Quando uma posição atinge o horário de vencimento + quarentena (60s), consulta o oráculo da Binance (direção da vela) e calcula o PnL determinístico, registrando o trade.

Servidor Flask (Dashboard)
API REST na porta 8516 para monitoramento em tempo real: status do bot, posições abertas, diagnósticos, configurações e sinais do radar.

📊 Entrada de Dados — WebSocket Binance
O bot consome três streams de kline 15m da Binance:

text
btcusdt@kline_15m
ethusdt@kline_15m
solusdt@kline_15m
Cada candle armazena:

timestamp, open, high, low, close, volume

taker_buy_vol – volume comprado agressivamente (fundamental para o Volume Delta)

Uma seed REST preenche o histórico inicial com 200 candles. Durante a execução, cada novo candle é atualizado via WebSocket em tempo real.

🎯 Radar — Tomada de Decisão
Fase 1: Indicadores Individuais por Ativo
Para cada ativo, a função decidir_radar() calcula dois indicadores sobre a vela em formação:

Bollinger Band Width (BBW)
Período: 50 candles

Cálculo: BBW = (Upper Band - Lower Band) / SMA(50)

Percentil: posição do BBW atual nos últimos 100 valores

Squeeze é ativado quando o BBW atual está ≤ percentil 20 (compressão da volatilidade)

Volume Delta
Extraído do taker_buy_vol acumulado até o segundo 898

delta_buy = taker_buy_vol / volume_total

Valores altos (>0.70) indicam pressão compradora dominante; valores baixos (<0.30), pressão vendedora.

Primeira decisão (por ativo):

Squeeze + delta_buy ≥ 0.70 → SNIPER_UP (só lado UP)

Squeeze + delta_buy ≤ 0.30 → SNIPER_DOWN (só lado DOWN)

Sem squeeze ou delta entre 0.31 e 0.69 → MALHA (ambos os lados)

Se os indicadores falham (dados insuficientes), assume-se MALHA como fallback.

Fase 2: Estratégia Consolidada — E4+Base1.1+Ind1.2+BBWalto
A decisão individual é refinada pela função decidir_estrategia(), que aplica regras sobre o conjunto dos três ativos:

GATE E4
Conta quantas das três velas anteriores (BTC, ETH, SOL) foram de alta (↑) ou de baixa (↓).
Se houver maioria (2x1 ou 3x0), o gate abre. Empate (1x1x1 ou sem dados) → SEM_SINAL.

Filtro BBW
Calcula o BBW percentil médio dos três ativos.
Se BBW_medio < 46% → mercado comprimido, sem sinal.

Filtro de Ambigüidade (Diff Mínimo)
Soma os deltas de compra dos três ativos (soma_buy = delta_BTC + delta_ETH + delta_SOL) e calcula a diferença absoluta para a soma de venda (diff = |soma_buy - (300 - soma_buy)|).
Se diff < 5 → sinal ambíguo, sem sinal.

Direção – Base1.1

Se ambas as somas (buy e sell) estiverem dentro do intervalo [120, 154]:
Direção definida pelo delta → soma_buy > soma_sell → UP, caso contrário DOWN.

Se alguma soma estiver fora do intervalo (pressão extrema):
Direção definida pelo consenso das velas (E4) → se maioria UP, SNIPER_UP; se maioria DOWN, SNIPER_DOWN.

O resultado final para cada ativo é SNIPER_UP, SNIPER_DOWN, ou SEM_SINAL.
(Quando a estratégia indica SEM_SINAL, o worker correspondente não posta ordens naquela vela.)

📝 Ordem de Escada (Ladder) e Tipos de Operação
As ordens são lançadas no segundo 899 da vela atual (T-1s), sempre nos tokens da vela seguinte. O worker busca previamente os mercados da Polymarket para o próximo ciclo.

Escada Base
Ordem	Token	Quantidade (cotas)	Preço Limite	Descrição
P1	Token UP	5	$0.54	Imediata – captura tendência alta
P2	Token UP	10	$0.35	Imediata – reforço na alta
P3	Token UP	10	$0.15	Imediata – proteção extrema
D1	Token DOWN	5	$0.54	Imediata – captura tendência baixa
D2	Token DOWN	10	$0.35	Imediata – reforço na baixa
D3	Token DOWN	10	$0.15	Imediata – proteção extrema
Modos de postagem:

SNIPER_UP: apenas P1, P2, P3

SNIPER_DOWN: apenas D1, D2, D3

MALHA: todos os seis (P1..P3 + D1..D3)

Ordens One-Cancels-Other (OCO) Manual
O próprio worker implementa uma lógica OCO:

Se P1 é preenchido antes de D1, D2 e D3 são cancelados imediatamente (supõe-se que o viés de alta é confirmado, e não se quer mais exposição baixista).

Se D1 é preenchido antes de P1, P2 e P3 são cancelados.

As ordens não preenchidas são automaticamente canceladas no início da vela seguinte (reset do ciclo).
🔮 Liquidação e Oráculo Binance
Quando uma ordem é preenchida, a posição é registrada com:

Token ID, preço de entrada, quantidade

Timestamp do ciclo alvo (ciclo_ts)

Timestamp de vencimento (market_close_ts)

O Monitor de Posições verifica cada posição a cada 0.2s. Ao atingir market_close_ts + 60s (quarentena anti-state bleed), consulta o candle fechado da Binance correspondente àquele ciclo:

Se o preço de fechamento for maior que a abertura → token UP vence (
1.00
)
,
D
O
W
N
p
e
r
d
e
(
1.00),DOWNperde(0.00).

Caso contrário → token DOWN vence ($1.00), UP perde.

O PnL é calculado como:
PnL = (preço de saída − preço de entrada) × cotas

Todas as operações são registradas no arquivo logs/assimetria_trades.csv.

⚙️ Configuração (.env)
O bot utiliza variáveis de ambiente para segurança e flexibilidade:

env
PRIVATE_KEY=0x...        # Chave privada da carteira (Polygon)
FUNDER_ADDRESS=0x...     # Endereço do funder (deve coincidir com a chave)
TRADE_REAL=false         # false = simulação, true = opera na Polymarket
Modo simulação: Quando TRADE_REAL=false, as ordens não são enviadas à Polymarket. O bot mantém um registro interno e simula fills com uma probabilidade por tick, usando o order book real para determinar se o preço limite foi atingido.

🚀 Como Executar
Instale as dependências:

text
pip install ccxt flask websockets web3 numpy pandas python-dotenv py_clob_client requests
Configure o arquivo .env com suas credenciais.

Execute o bot:

text
python nome_do_arquivo.py
Acesse o dashboard em http://localhost:8516.

🌐 Endpoints da API Flask
Rota	Descrição
/	Estado geral do bot (balance, win rate, logs, etc.)
/status	Status resumido + diagnósticos da estratégia
/positions	Lista de posições abertas
/config	Parâmetros da estratégia
/sinal_radar	Último sinal do radar por ativo
/pause	Pausa o bot (não abre novas posições)
/resume	Reativa o bot
📁 Arquivos de Log e Dados
logs/assimetria_YYYY-MM-DD.log – Log geral da execução.

logs/assimetria_trades.csv – Histórico de trades.

logs/radar_velas.csv – Sinais do radar e resultados das velas.

📘 Glossário
BBW: Bollinger Band Width – largura das bandas de Bollinger.

Squeeze: estado de baixa volatilidade, onde as bandas estão contraídas.

Volume Delta: fração do volume negociado de forma agressiva (compra vs venda).

SNIPER_UP / SNIPER_DOWN: decisão de operar apenas um lado (alta ou baixa).

MALHA: operar ambos os lados simultaneamente.

Kill Switch: mecanismo que cancela ordens do lado perdedor e ativa proteção.

Quarentena: espera de 60s após o vencimento para usar o preço de fechamento da Binance

"""

import os, time, json, math, csv, threading, requests
import asyncio
import websockets
from collections import deque
from threading import RLock, Event
import numpy as np
import pandas as pd
import ccxt
from datetime import datetime, timezone
from flask import Flask, jsonify
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType, ApiCreds
from py_clob_client.order_builder.constants import BUY, SELL
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# ─── CONFIGURAÇÕES GERAIS ─────────────────────────────────────
load_dotenv()

SYMBOLS      = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']
TIMEFRAME    = '15m'
CANDLE_LIMIT = 200

from web3 import Web3
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
if not PRIVATE_KEY: raise RuntimeError("PRIVATE_KEY não definida.")
FUNDER_ADDRESS_BRUTO = os.getenv("FUNDER_ADDRESS")
if not FUNDER_ADDRESS_BRUTO: raise RuntimeError("FUNDER_ADDRESS não definido.")
FUNDER_ADDRESS = Web3.to_checksum_address(FUNDER_ADDRESS_BRUTO)

SIGNATURE_TYPE = 2
CHAIN_ID       = 137
HOST           = "https://clob.polymarket.com"
TRADE_REAL     = os.getenv("TRADE_REAL", "false").lower() == "true"

# ══════════════════════════════════════════════════════════════
# ESTRATÉGIA: MÁQUINA DE CONDOR BIDIRECIONAL v3.0
# ══════════════════════════════════════════════════════════════
# Bot dispara DOIS lados independentes por vela (lado P=UP, lado D=DOWN).
# Radar BTC aos T-10s decide: Sniper UP / Sniper DOWN / Malha de Guerra.
# Kill Switch dispara em função separada quando P4 ou D4 preenchem.

# ── Lado P (token UP) ─────────────────────────────────────────
P1_COTAS = 5;   P1_PRECO = 0.54      # imediata
P2_COTAS = 10;  P2_PRECO = 0.35      # imediata
P3_COTAS = 10;  P3_PRECO = 0.15      # imediata

# ── Lado D (token DOWN, espelho) ──────────────────────────────
D1_COTAS = 5;   D1_PRECO = 0.54      # imediata
D2_COTAS = 10;  D2_PRECO = 0.35      # imediata
D3_COTAS = 10;  D3_PRECO = 0.15      # imediata

# ── Radar BTC: BBW + Volume Delta ─────────────────────────────
BBW_PERIODO            = 50          # janela das Bollinger Bands
BBW_SQUEEZE_PERCENTIL  = 20          # percentil p/ classificar Squeeze
BBW_PERCENTIL_LOOKBACK = 100         # janela p/ calcular o percentil
DELTA_THRESHOLD        = 0.70        # 50% — sniper; entre 0.31 e 0.69 = misto
RADAR_T_SEG            = 898         # T-2s da vela (14m58s)
POSTAGEM_T_SEG         = 899         # T-1s da vela  (14m59s)

# ── Tempos / poll ─────────────────────────────────────────────
POLL_FILL_INTERVAL     = 0.3         # intervalo de polling (s)
SENTINELA_PRECO        = 0.735       # gatilho de disparo do Sentinela (D4/P4)
QUARENTENA_PNL_S       = 60.0        # quarentena pós-vencimento

# ── Banca / Controle ──────────────────────────────────────────
BANCA_INICIAL        = 1000.00
BANCA_TETO_SIMULACAO = 2000.00
MAX_SPREAD           = 0.035
SCAN_INTERVAL        = 1.0

FLASK_PORT = 8516

# ══════════════════════════════════════════════════════════════
# LOGGING
# ══════════════════════════════════════════════════════════════
Path("logs").mkdir(exist_ok=True)
log_filename = f"logs/assimetria_{datetime.now().strftime('%Y-%m-%d')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[
        logging.FileHandler(log_filename, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
def log(msg: str): logging.info(msg)
def ts(): return time.strftime('%H:%M:%S')

# ══════════════════════════════════════════════════════════════
# WEBSOCKET BINANCE (idêntico ao Grid Maker)
# ══════════════════════════════════════════════════════════════
WS_STREAM_MAP = {
    "BTC": "btcusdt@kline_15m",
    "ETH": "ethusdt@kline_15m",
    "SOL": "solusdt@kline_15m",
}
WS_STREAM_REVERSE = {v: k for k, v in WS_STREAM_MAP.items()}
_raw_deques  = {a: deque(maxlen=CANDLE_LIMIT) for a in WS_STREAM_MAP}
_deque_locks = {a: RLock()                    for a in WS_STREAM_MAP}
ws_ready     = {a: Event()                    for a in WS_STREAM_MAP}
_WS_URL = ("wss://data-stream.binance.com/stream?streams="
           + "/".join(WS_STREAM_MAP.values()))
_WS_BACKOFF_INIT = 1; _WS_BACKOFF_MAX = 60

def _seed_rest(asset, exch):
    """
    Seed via REST. A API da Binance retorna 12 colunas por kline:
      [0]ts  [1]o  [2]h  [3]l  [4]c  [5]v  [6]close_ts  [7]quote_vol
      [8]num_trades  [9]taker_buy_base_vol  [10]taker_buy_quote_vol  [11]ignore

    O fetch_ohlcv do ccxt corta nas primeiras 6 colunas. Para capturar o
    Taker Buy Volume (índice 9) — necessário pro cálculo de Volume Delta —
    chamamos o endpoint REST direto.
    """
    try:
        symbol = f"{asset}USDT"
        url    = "https://api.binance.com/api/v3/klines"
        params = {"symbol": symbol, "interval": TIMEFRAME, "limit": CANDLE_LIMIT}
        r = requests.get(url, params=params, timeout=10)
        if r.status_code != 200:
            log(f"[{ts()}] ❌ Seed {asset}: HTTP {r.status_code}")
            return False
        klines = r.json()
        if not klines:
            return False
        with _deque_locks[asset]:
            _raw_deques[asset].clear()
            for k in klines:
                # [ts, open, high, low, close, volume, taker_buy_base_vol]
                bar = [int(k[0]), float(k[1]), float(k[2]), float(k[3]),
                       float(k[4]), float(k[5]), float(k[9])]
                _raw_deques[asset].append(bar)
        log(f"[{ts()}] 🌱 Seed {asset}: {len(klines)} candles (com taker_buy_vol).")
        return True
    except Exception as e:
        log(f"[{ts()}] ❌ Seed {asset}: {e}")
        return False

def _ws_apply_kline(asset, k):
    """
    Aplica kline recebido via WebSocket.
    Campos do payload Binance kline:
      t = open time (ms)
      o, h, l, c, v = OHLCV padrão
      V = taker buy base asset volume (volume de COMPRA agressiva)
    O Volume Delta = V / v  → fração de agressão compradora vs total.
    """
    ts_ms = int(k["t"])
    try:
        taker_buy = float(k.get("V", 0.0))
    except (TypeError, ValueError):
        taker_buy = 0.0
    bar = [ts_ms, float(k["o"]), float(k["h"]), float(k["l"]),
           float(k["c"]), float(k["v"]), taker_buy]
    with _deque_locks[asset]:
        if _raw_deques[asset] and _raw_deques[asset][-1][0] == ts_ms:
            _raw_deques[asset][-1] = bar
        else:
            _raw_deques[asset].append(bar)

def ws_get_dataframe(asset):
    """
    Retorna DataFrame com colunas:
      open, high, low, close, volume, taker_buy_vol
    indexado por datetime (UTC).
    """
    with _deque_locks[asset]:
        if len(_raw_deques[asset]) < 30:
            return None
        rows = list(_raw_deques[asset])
    df = pd.DataFrame(
        rows,
        columns=["timestamp", "open", "high", "low",
                 "close", "volume", "taker_buy_vol"]
    )
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df.set_index("datetime").drop(columns=["timestamp"])

async def _ws_listener():
    backoff = _WS_BACKOFF_INIT
    while True:
        try:
            log(f"[{ts()}] 🔌 [ASSIM] WS: conectando...")
            async with websockets.connect(
                _WS_URL, ping_interval=20, ping_timeout=10,
                close_timeout=5, max_size=2**20
            ) as ws:
                log(f"[{ts()}] ✅ [ASSIM] WS: conexão estabelecida.")
                backoff = _WS_BACKOFF_INIT
                async for raw in ws:
                    try:
                        msg    = json.loads(raw)
                        stream = msg.get("stream", "")
                        k      = msg.get("data", {}).get("k")
                        if not k or stream not in WS_STREAM_REVERSE: continue
                        asset  = WS_STREAM_REVERSE[stream]
                        _ws_apply_kline(asset, k)
                        if not ws_ready[asset].is_set():
                            ws_ready[asset].set()
                            log(f"[{ts()}] 🟢 [ASSIM] WS: {asset} LIVE.")
                    except Exception: pass
        except Exception as e:
            log(f"[{ts()}] ⚠️ [ASSIM] WS: {e}. Reconectando em {backoff}s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _WS_BACKOFF_MAX)

def _ws_thread_main():
    exch = ccxt.binance({"enableRateLimit": True})
    for a in WS_STREAM_MAP:
        if _seed_rest(a, exch): ws_ready[a].set()
    asyncio.run(_ws_listener())

def iniciar_ws_manager():
    t = threading.Thread(
        target=_ws_thread_main, daemon=True, name="assim_ws_manager")
    t.start()
    log(f"[{ts()}] 📡 [ASSIM] WS Manager iniciado.")
    return t

# ══════════════════════════════════════════════════════════════
# POLYMARKET — INICIALIZAÇÃO
# ══════════════════════════════════════════════════════════════
exchange = ccxt.binance({'enableRateLimit': True})
try:
    log(f"[{ts()}] 🛰️  [ASSIM] Conectando Polymarket...")
    auth_client = ClobClient(
        HOST, key=PRIVATE_KEY, chain_id=CHAIN_ID,
        signature_type=SIGNATURE_TYPE, funder=FUNDER_ADDRESS)
    creds = auth_client.create_or_derive_api_creds()
    auth_client.set_api_creds(creds)
    auth_client.get_api_keys()
    WEB3_STATUS = f"CONECTADO (sig={SIGNATURE_TYPE})"
    log(f"[{ts()}] ✅ [ASSIM] {FUNDER_ADDRESS[:6]}...{FUNDER_ADDRESS[-4:]}")
except Exception as e:
    auth_client = None
    WEB3_STATUS = "ERRO_AUTH"
    log(f"[{ts()}] ❌ [ASSIM] {e} → MODO SIMULAÇÃO")

# ══════════════════════════════════════════════════════════════
# ESTADO GLOBAL
# ══════════════════════════════════════════════════════════════
state_lock     = threading.RLock()
positions_lock = threading.RLock()

state = {
    "balance":        BANCA_INICIAL,
    "initial_balance": BANCA_INICIAL,
    "peak_balance":   BANCA_INICIAL,
    "history":        [BANCA_INICIAL],
    "logs":           [],
    "status":         "ATIVO",
    "win_rate":       0.0,
    "trades_count":   0,
    "wins":           0,
    "web3_status":    WEB3_STATUS,
    "trade_mode":     "REAL" if TRADE_REAL else "SIMULAÇÃO",
    "open_positions": 0,
    # Status por ativo
    "assimetria_status": {
        "BTC": "IDLE",
        "ETH": "IDLE",
        "SOL": "IDLE",
    },
    # Contadores de diagnóstico (Condor Bidirecional)
    "diag_velas":          0,    # velas processadas
    "diag_sniper_up":      0,    # decisão A: só lado P
    "diag_sniper_down":    0,    # decisão B: só lado D
    "diag_malha":          0,    # decisão C: ambos
    "diag_p1_fills":       0, "diag_p2_fills": 0, "diag_p3_fills": 0,
    "diag_d1_fills":       0, "diag_d2_fills": 0, "diag_d3_fills": 0,
    "diag_kill_switch_up": 0,    # P4 preenchida → cancelou D1/D2/D3
    "diag_kill_switch_dn": 0,    # D4 preenchida → cancelou P1/P2/P3
    "diag_wins":           0,
    "diag_losses":         0,
    # Última leitura do radar (p/ dashboard)
    "radar_por_ativo": {
        "BTC": {"decisao": "AGUARDANDO", "bbw": 0.0, "bbw_perc": 0.0, "delta": 0.5, "squeeze": False},
        "ETH": {"decisao": "AGUARDANDO", "bbw": 0.0, "bbw_perc": 0.0, "delta": 0.5, "squeeze": False},
        "SOL": {"decisao": "AGUARDANDO", "bbw": 0.0, "bbw_perc": 0.0, "delta": 0.5, "squeeze": False},
    },
}

positions     = {}   # posições abertas (perna preenchida aguardando vencimento)
csv_lock      = threading.Lock()

# ── Buffer de radar para CSV (coordinator grava quando vela fecha) ────
_radar_csv_buffer = {}  # {ciclo_ts: {"BTC": {...}, "ETH": {...}, "SOL": {...}}}

# ── CSV de trades ─────────────────────────────────────────────
TRADES_CSV    = "logs/assimetria_trades.csv"
RADAR_CSV     = "logs/radar_velas.csv"
RADAR_CSV_HDR = [
    "vela_ts", "ativo", "bbw", "bbw_perc", "squeeze",
    "delta_buy", "delta_sell", "decisao",
    "vela_dir", "open", "high", "low", "close", "var_pct",
]
TRADES_HEADER = [
    "DataHora_Saida", "DataHora_Entrada", "Ativo", "Direcao",
    "Preco_Entrada", "Preco_Saida", "Cotas",
    "Motivo_Saida", "PnL_USD", "PnL_PCT"
]

def log_event(msg_type, market, val="0.00"):
    with state_lock:
        state["logs"].insert(0, {
            "type": msg_type, "time": ts(), "val": val, "market": market})
        state["logs"] = state["logs"][:200]

def record_trade(entry, exit_p, cotas, question, reason,
                 asset="?", direction="up", entry_time=None):
    pnl     = (exit_p - entry) * cotas
    pnl_pct = ((exit_p / max(entry, 0.001)) - 1) * 100
    with state_lock:
        state["balance"] += pnl
        if pnl > 0:
            state["wins"] += 1
            state["diag_wins"] += 1
        else:
            state["diag_losses"] += 1
        state["trades_count"] += 1
        state["win_rate"] = (state["wins"] / max(state["trades_count"], 1)) * 100
        state["history"].append(round(state["balance"], 2))
        state["history"] = state["history"][-500:]
        if state["balance"] > state["peak_balance"]:
            state["peak_balance"] = state["balance"]
        log_event("win" if pnl > 0 else "loss", question[:30], f"{abs(pnl):.2f}")
        if state["balance"] < state["peak_balance"] * 0.70:
            state["status"] = "PAUSADO"
            log(f"[{ts()}] 🚨 [ASSIM] CIRCUIT BREAKER: drawdown>30% — pausado.")
    dte = entry_time.strftime("%Y-%m-%d %H:%M:%S") if entry_time else "N/A"
    with csv_lock:
        if not Path(TRADES_CSV).exists():
            with open(TRADES_CSV, mode='w', newline='', encoding='utf-8') as f:
                csv.writer(f).writerow(TRADES_HEADER)
        with open(TRADES_CSV, mode='a', newline='', encoding='utf-8') as f:
            csv.writer(f).writerow([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"), dte,
                asset, direction.upper(),
                round(entry, 4), round(exit_p, 4), round(cotas, 4),
                reason, round(pnl, 4), round(pnl_pct, 2)
            ])

            # ══════════════════════════════════════════════════════════════
# POLYMARKET — MERCADO / ORDERBOOK / EXECUÇÃO
# ══════════════════════════════════════════════════════════════
ASSET_SLUG = {"BTC": "btc", "ETH": "eth", "SOL": "sol"}

def fetch_crypto_market(asset, direction, target_ciclo_ts=None):
    """
    Busca mercado UP ou DOWN.
    - Sem target_ciclo_ts: tenta ciclo atual → próximo → anterior (legado).
    - Com target_ciclo_ts: busca EXCLUSIVAMENTE esse ciclo.
      Usado pelo pré-fetch para garantir que NÃO pegue o mercado
      que está prestes a fechar (bug que invalidava ordens BTC/ETH).
    """
    coin   = ASSET_SLUG.get(asset.upper(), asset.lower())
    now_ts = int(time.time())

    if target_ciclo_ts is not None:
        candidate_bases = [target_ciclo_ts]              # busca cirúrgica
    else:
        base = now_ts - (now_ts % 900)
        candidate_bases = [base, base + 900, base - 900] # legado

    for mb in candidate_bases:
        slug = f"{coin}-updown-15m-{mb}"
        try:
            r = requests.get(
                f"https://gamma-api.polymarket.com/events?slug={slug}", timeout=6)
            if r.status_code != 200: continue
            data = r.json()
            if not data: continue
            event   = data[0] if isinstance(data, list) else data
            markets = event.get("markets", [])
            if not markets: continue
            market  = markets[0]
            if not market.get("active", False): continue
            if market.get("closed", True): continue
            if market.get("acceptingOrders") is False: continue
            eds = market.get("endDate")
            try:
                end_ts = int(
                    datetime.fromisoformat(
                        eds.replace('Z', '+00:00')).timestamp()) if eds else mb + 900
            except: end_ts = mb + 900
            if end_ts <= time.time(): continue
            if target_ciclo_ts is not None:
                # Busca cirúrgica: aceita só se o end_ts bater com o
                # fim do ciclo alvo (tolerância 120s p/ drift do endDate).
                if abs(end_ts - (target_ciclo_ts + 900)) > 120: continue
            else:
                jaf = now_ts - (now_ts % 900) + 900
                if end_ts > jaf + 120: continue
            outcomes = market.get('outcomes', [])
            outcomes = json.loads(outcomes) if isinstance(outcomes, str) else outcomes
            idx = next(
                (i for i, o in enumerate(outcomes)
                 if o.strip().lower() == direction.lower()), -1)
            if idx == -1: continue
            prices = market.get('outcomePrices', '[]')
            prices = json.loads(prices) if isinstance(prices, str) else prices
            price  = float(prices[idx])
            if not (0.05 <= price <= 0.95): continue
            tokens = market.get('clobTokenIds', '[]')
            tokens = json.loads(tokens) if isinstance(tokens, str) else tokens
            if idx >= len(tokens): continue
            return {
                'token_id':        tokens[idx],
                'price':           price,
                'question':        f"{event.get('title', slug)} ({direction.upper()})",
                'market_close_ts': end_ts,
            }
        except Exception as e:
            log(f"[{ts()}] ⚠️ [ASSIM] {slug}: {e}")
            continue
    return None

def get_book(token_id):
    empty = {"ok": False, "best_bid": None, "best_ask": None,
             "mid": None, "imbalance": 0.5}
    try:
        r = requests.get(
            f"https://clob.polymarket.com/book?token_id={token_id}", timeout=5)
        if r.status_code != 200: return empty
        d    = r.json()
        bids = sorted(d.get('bids', []), key=lambda x: float(x['price']), reverse=True)
        asks = sorted(d.get('asks', []), key=lambda x: float(x['price']))
        if not bids or not asks: return empty
        bb  = float(bids[0]['price']); ba = float(asks[0]['price'])
        vb  = sum(float(b.get('size', 0)) for b in bids[:5])
        va  = sum(float(a.get('size', 0)) for a in asks[:5])
        tot = vb + va
        return {
            "ok": True, "best_bid": bb, "best_ask": ba, "mid": (bb + ba) / 2,
            "imbalance": vb / tot if tot > 0 else 0.5,
        }
    except: return empty

# ── Modo Simulação — controlado pelo .env TRADE_REAL ─────────
MODO_SIMULACAO = not TRADE_REAL

# Registro interno de ordens simuladas
# { oid: {token_id, limit_price, filled, fill_price, cancelled, created_at} }
_sim_orders: dict = {}
_sim_orders_lock  = threading.Lock()

# Probabilidade de fill por tick (~0.3s): ~8% → fill em ~3-4s em média
SIM_FILL_PROB_PER_TICK = 0.08

import random as _random   # usado só no simulador


def execute_limit_buy(token_id, price, size, label=""):
    """
    Posta ordem LIMIT BUY (GTC Maker).
    MODO_SIMULACAO=True  → registra localmente, zero chamada real.
    MODO_SIMULACAO=False → chama API Polymarket com retry anti-425.
    """
    sp = round(min(max(price, 0.01), 0.99), 2)
    ss = max(int(math.floor(size)), 1)

    # ── SIMULAÇÃO ────────────────────────────────────────────
    if MODO_SIMULACAO:
        oid = f"sim_{label}_{int(time.time() * 1000)}"
        with _sim_orders_lock:
            _sim_orders[oid] = {
                "token_id":    token_id,
                "limit_price": sp,
                "filled":      False,
                "fill_price":  0.0,
                "cancelled":   False,
                "created_at":  time.time(),
            }
        log(f"[{ts()}] 📋 [SIMULAÇÃO] Ordem LIMIT BUY enviada com sucesso | "
            f"{label} | {ss}c @ ${sp:.2f} | OID={oid}")
        return {"status": "success", "orderID": oid}

    # ── PRODUÇÃO — Retry dinâmico anti-425 ───────────────────
    if not auth_client:
        log(f"[{ts()}] ❌ [ASSIM] LIMIT {label}: sem auth_client.")
        return {"status": "error", "message": "sem auth"}

    RETRY_MAX       = 15
    RETRY_SLEEP_S   = 2.0
    ERROS_425       = ("425", "service not ready", "too early")

    for tentativa in range(1, RETRY_MAX + 1):
        try:
            signed = auth_client.create_order(
                OrderArgs(token_id=token_id, price=sp, size=ss, side=BUY))
            resp = auth_client.post_order(signed, OrderType.GTC)
            if resp and resp.get('success'):
                oid = resp.get('orderID', '?')
                sufixo = f" (tentativa {tentativa})" if tentativa > 1 else ""
                log(f"[{ts()}] ✅ [ASSIM] LIMIT {label} @ ${sp} | {ss}c | {oid}{sufixo}")
                return {"status": "success", "orderID": oid}
            # Erro de negócio (saldo, mercado fechado) — não faz retry
            log(f"[{ts()}] ❌ [ASSIM] LIMIT {label} rejeitado: {resp}")
            return {"status": "error", "message": str(resp)}

        except Exception as e:
            erro_str = str(e).lower()
            is_425   = any(k in erro_str for k in ERROS_425)

            if is_425 and tentativa < RETRY_MAX:
                log(f"[{ts()}] 🔁 [RETRY] Mercado não pronto (425). "
                    f"Tentando novamente em {RETRY_SLEEP_S}s... "
                    f"(Tentativa {tentativa}/{RETRY_MAX}) | {label}")
                time.sleep(RETRY_SLEEP_S)
                continue

            if is_425:
                log(f"[{ts()}] ❌ [ASSIM] LIMIT {label}: 425 persistiu após "
                    f"{RETRY_MAX} tentativas ({RETRY_MAX*RETRY_SLEEP_S:.0f}s). Desistindo.")
            else:
                log(f"[{ts()}] ❌ [ASSIM] LIMIT {label}: {e}")
            return {"status": "error", "message": str(e)}

    return {"status": "error", "message": "retry_esgotado"}

def cancel_order(oid, label=""):
    """
    Cancela ordem.
    MODO_SIMULACAO → marca cancelled=True no dict local.
    Produção       → chama API Polymarket.
    """
    if not oid:
        return True

    # ── SIMULAÇÃO ────────────────────────────────────────────
    if MODO_SIMULACAO or oid.startswith("sim_"):
        with _sim_orders_lock:
            if oid in _sim_orders:
                if _sim_orders[oid]["filled"]:
                    log(f"[{ts()}] ⚠️  [SIMULAÇÃO] Cancel {label} ignorado — "
                        f"OID {oid[:22]} já preenchida.")
                    return False
                _sim_orders[oid]["cancelled"] = True
        log(f"[{ts()}] 🗑️  [SIMULAÇÃO] Cancel {label} | {oid[:24]}")
        return True

    # ── PRODUÇÃO ─────────────────────────────────────────────
    if not auth_client:
        return False
    try:
        auth_client.cancel(oid)
        log(f"[{ts()}] 🗑️  [ASSIM] Cancel {label} {oid[:12]}...")
        return True
    except Exception as e:
        log(f"[{ts()}] ⚠️ [ASSIM] cancel {label} {oid[:10]}: {e}")
        return False

def check_order_fill(oid):
    """
    Retorna (filled: bool, price: float).
    MODO_SIMULACAO → sorteia fill estocástico no dict local.
    Produção       → consulta API Polymarket.
    """
    if not oid:
        return False, 0.0

    # ── SIMULAÇÃO ────────────────────────────────────────────
    if MODO_SIMULACAO or oid.startswith("sim_"):
        with _sim_orders_lock:
            entry = _sim_orders.get(oid)
            if entry is None:
                return False, 0.0
            if entry.get("cancelled"):
                return False, 0.0
            if entry["filled"]:
                return True, entry["fill_price"]
            # Sorteio: simula o mercado atingindo o preço limite
            if _random.random() < SIM_FILL_PROB_PER_TICK:
                lp = entry["limit_price"]
                entry["filled"]     = True
                entry["fill_price"] = lp
                log(f"[{ts()}] 🎲 [SIMULAÇÃO] FILL simulado | "
                    f"OID={oid[:24]} @ ${lp:.3f}")
                return True, lp
        return False, 0.0

    # ── PRODUÇÃO ─────────────────────────────────────────────
    if not auth_client:
        return False, 0.0
    try:
        o  = auth_client.get_order(oid)
        sm = float(o.get("size_matched", 0) or 0)
        st = float(o.get("original_size", 1) or 1)
        pr = float(o.get("price", 0) or 0)
        return sm >= st * 0.99, pr
    except Exception as e:
        log(f"[{ts()}] ⚠️ [ASSIM] fill {oid[:8]}: {e}")
        return False, 0.0

def check_fill_sim(token_id, limit_price):
    """
    Simulação de fill LIMIT BUY — REGRA ÚNICA para UP e DOWN.
    ════════════════════════════════════════════════════════
    LIMIT BUY casa contra ASK (alguém vendendo). Logo:
      fill ⇔ best_ask <= limit_price + tolerância

    A tolerância de 0.015 (1.5¢) modela o spread real médio do
    Polymarket, replicando o comportamento do Grid Maker que
    opera bem em produção.

    Por que NÃO usar mid:
      mid pode estar baixo só porque o bid afundou; se o ask
      continua alto, NÃO há venda disponível e a ordem fica
      parada no livro. Usar mid produzia fills fantasma quando
      o mercado ia contra a posição (bug crítico v2.0).

    Aplicada IDENTICAMENTE a UP e DOWN — comprar token P/UP ou
    token D/DOWN tem a mesma mecânica de casamento, muda só
    qual token você está olhando.
    """
    book = get_book(token_id)
    if not book["ok"]:
        return False, limit_price
    ask = book.get("best_ask")
    if ask is None:
        return False, limit_price
    # Fill exige ask válido (>= 0.01) e <= limite + tolerância de 1.5¢
    if 0.01 <= ask <= limit_price + 0.015:
        return True, ask          # retorna preço REAL (price improvement)
    return False, limit_price


def check_fill_sim_down(token_id, limit_price):
    """
    DEPRECATED — alias para check_fill_sim.

    A função antiga invertia a regra (preenchia quando o token DOWN
    SUBIA), produzindo fills mágicos em mercados que derretiam.
    LIMIT BUY de DOWN tem a MESMA mecânica de LIMIT BUY de UP:
    você está comprando um token; só casa se houver venda no
    seu preço. Não existe regra "para baixo".

    Mantida só para não quebrar chamadas legadas do worker antigo.
    """
    return check_fill_sim(token_id, limit_price)

# ══════════════════════════════════════════════════════════════
# MONITOR DE POSIÇÕES — Vencimento com Oráculo Binance
# ══════════════════════════════════════════════════════════════
def monitor_positions():
    log(f"[{ts()}] 🛡️  [ASSIM] Monitor de posições iniciado.")
    while True:
        try:
            time.sleep(0.2)
            now    = datetime.now()
            to_close = []

            with positions_lock:
                snap = list(positions.items())

            for dk, pos in snap:
                try:
                    tid     = pos.get('token_id', dk)
                    entry   = pos['entry_price']
                    cotas   = pos['cotas']
                    asset   = pos.get('asset', '?')
                    direction = pos.get('direction', 'up')
                    phase     = pos.get('phase', '?')
                    mct     = pos.get('market_close_ts')
                    ciclo_ts_pos = pos.get('ciclo_ts', 0)

                    if not mct:
                        continue

                    now_ts = time.time()

                    # ── Vencimento natural ──────────────────────
                    if now_ts < mct:
                        continue  # ainda dentro da vela — aguarda

                    segundos_apos = now_ts - mct

                    # Quarentena 60s (anti-State-Bleed)
                    if segundos_apos < QUARENTENA_PNL_S:
                        continue

                    # Guarda de ciclo
                    ciclo_ativo_agora = int(now_ts) // 900 * 900
                    if ciclo_ts_pos >= ciclo_ativo_agora:
                        continue   # aguarda próximo ciclo (silencioso)

                    # ── Oráculo Binance ──────────────────────────
                    # Tese: se BTC/ETH/SOL SUBIU na vela, token UP resolve
                    # em $1.00 e DOWN em $0.00. Se desceu, vice-versa.
                    # A coluna `direction` da posição diz QUAL TOKEN ela
                    # segura (não a tese de aposta) — então:
                    #   token UP   → vence se subiu
                    #   token DOWN → vence se desceu
                    # Isso cobre P4 (token DOWN, comprado em malha UP) e
                    # D4 (token UP, comprado em malha DOWN) corretamente.
                    vencedora = None
                    try:
                        df_asset = ws_get_dataframe(asset)
                        if df_asset is not None and len(df_asset) >= 2:
                            ciclo_start = ciclo_ts_pos
                            bar_ciclo = None
                            for idx in range(len(df_asset) - 1, -1, -1):
                                bar_ts = int(df_asset.index[idx].timestamp())
                                if bar_ts <= ciclo_start:
                                    bar_ciclo = df_asset.iloc[idx]
                                    break
                            if bar_ciclo is None:
                                log(f"[{ts()}] ⚠️ [CONDOR] Oráculo {asset}: "
                                    f"barra do ciclo não encontrada.")
                                continue
                            preco_abertura   = float(bar_ciclo["open"])
                            preco_fechamento = float(bar_ciclo["close"])
                            subiu = preco_fechamento > preco_abertura
                            log(f"[{ts()}] 🕯️ [CONDOR] Barra usada: "
                                f"{df_asset.index[idx]} | "
                                f"Open={preco_abertura:.2f} "
                                f"Close={preco_fechamento:.2f}")

                            # direction = 'up' (segura token UP) ou 'down'
                            if direction == "up":
                                vencedora = subiu
                            else:
                                vencedora = not subiu

                            log(f"[{ts()}] 🔮 [CONDOR] ORÁCULO {asset}: "
                                f"Abertura=${preco_abertura:.2f} | "
                                f"Fechamento=${preco_fechamento:.2f} | "
                                f"Subiu={subiu} | "
                                f"Token={direction.upper()}/Fase={phase} | "
                                f"Vencedora={vencedora}")
                    except Exception as e:
                        log(f"[{ts()}] ⚠️ [CONDOR] Oráculo {asset}: {e}")

                    # ── PnL determinístico ───────────────────────
                    if vencedora is True:
                        exit_p = 1.00
                        reason = f"{phase}_CONTRATO_VENCIDO_WIN"
                    elif vencedora is False:
                        exit_p = 0.00
                        reason = f"{phase}_CONTRATO_VENCIDO_LOSS"
                    else:
                        bf     = get_book(tid)
                        bbf    = bf.get("best_bid")
                        exit_p = bbf if (bf["ok"] and bbf and 0.01 < bbf < 0.99) else 0.01
                        reason = f"{phase}_CONTRATO_VENCIDO_FALLBACK"

                    pnl   = (exit_p - entry) * cotas
                    emoji = "🟢 WIN" if vencedora is True else (
                            "🔴 LOSS" if vencedora is False else "⚠️ FALLBACK")
                    log(f"[{ts()}] 🏁 [CONDOR] VENCIMENTO {asset} "
                        f"Token={direction.upper()}/{phase} | "
                        f"{emoji} | Entry=${entry:.3f} × {cotas}c | "
                        f"Exit=${exit_p:.3f} | PnL={pnl:+.2f}")

                    to_close.append(dk)
                    record_trade(
                        entry, exit_p, cotas,
                        pos.get('question', asset),
                        reason, asset=asset,
                        direction=direction,
                        entry_time=pos.get('entry_time'))
                    log_event("win" if pnl > 0 else "loss",
                              f"{asset} {direction.upper()}", f"{abs(pnl):.2f}")

                except Exception as e:
                    log(f"[{ts()}] ⚠️ [ASSIM] pos {dk[:16]}: {e}")

            with positions_lock:
                for dk in to_close:
                    positions.pop(dk, None)
                state["open_positions"] = len(positions)

        except Exception as e:
            log(f"[{ts()}] 💥 [ASSIM] MONITOR: {e}")
            time.sleep(0.5)

            # ══════════════════════════════════════════════════════════════
# RADAR BTC — BBW + Volume Delta (Cérebro Único da Frota)
# ══════════════════════════════════════════════════════════════
# Decisão tomada aos T-10s (seg 890) sobre a vela em formação.
# Aplica IDÊNTICA aos 3 ativos (BTC, ETH, SOL).
# Vocabulário:
#   "SNIPER_UP"   = só lado P (3 ordens)
#   "SNIPER_DOWN" = só lado D (3 ordens)
#   "MALHA"       = ambos os lados (6 ordens)

# Lock + dict compartilhado entre Coordenador (escreve) e Workers (leem)
sinal_lock = threading.RLock()
_sinal_vazio = {
    "ciclo_alvo":   0,
    "decisao":      None,
    "bbw_atual":    0.0,
    "bbw_percentil": 0.0,
    "squeeze":      False,
    "delta_buy":    0.5,
    "calculado_em": 0.0,
    "diagnostico":  "",
}
sinal_radar = {
    "BTC": dict(_sinal_vazio),
    "ETH": dict(_sinal_vazio),
    "SOL": dict(_sinal_vazio),
}


def calcular_bbw(asset):
    """
    Bollinger Band Width sobre kline 15m do ativo.
      BBW = (Upper - Lower) / Middle
      Upper = SMA(close, 50) + 2 * STD(close, 50)
      Lower = SMA(close, 50) - 2 * STD(close, 50)

    Retorna:
      (bbw_atual, percentil_atual, squeeze_bool)

    Squeeze = bbw_atual <= percentil 20 dos últimos 100 valores de BBW.
    """
    df = ws_get_dataframe(asset)
    if df is None or len(df) < (BBW_PERIODO + BBW_PERCENTIL_LOOKBACK + 5):
        return None, None, None, f"DataFrame {asset} insuficiente"

    closes = df["close"].astype(float)
    sma  = closes.rolling(BBW_PERIODO).mean()
    std  = closes.rolling(BBW_PERIODO).std(ddof=0)
    bbw_series = ((sma + 2 * std) - (sma - 2 * std)) / sma  # = 4*std/sma

    bbw_atual = float(bbw_series.iloc[-1])
    if pd.isna(bbw_atual):
        return None, None, None, "BBW=NaN"

    # Percentil do BBW atual nos últimos N valores (exclui o próprio)
    janela = bbw_series.iloc[-(BBW_PERCENTIL_LOOKBACK + 1):-1].dropna()
    if len(janela) < 30:
        return None, None, None, "Janela percentil insuficiente"

    # rank percentílico: % de valores da janela <= bbw_atual
    perc = float((janela <= bbw_atual).sum()) / len(janela) * 100.0
    squeeze = perc <= BBW_SQUEEZE_PERCENTIL
    return bbw_atual, perc, squeeze, ""


def calcular_volume_delta(asset):
    """
    Volume Delta sobre a VELA EM FORMAÇÃO do ativo (não fechada).
      delta_buy = taker_buy_vol / volume_total
      delta_sell = 1 - delta_buy

    Aos T-10s a vela já tem ~14m50s de fluxo acumulado, ou seja,
    ~98.9% da intenção direcional já está precificada.

    Retorna:
      (delta_buy: float em [0,1], diag_str)
      ou (None, motivo) em falha.
    """
    df = ws_get_dataframe(asset)
    if df is None or len(df) == 0:
        return None, f"DataFrame {asset} vazio"

    bar = df.iloc[-1]
    vol_total = float(bar["volume"])
    vol_buy   = float(bar["taker_buy_vol"])

    if vol_total <= 0:
        return None, "volume_total=0"
    if vol_buy < 0 or vol_buy > vol_total + 1e-6:
        # sanity check (vol_buy nunca pode passar de vol_total)
        return None, f"taker_buy inconsistente ({vol_buy:.4f}/{vol_total:.4f})"

    delta_buy = vol_buy / vol_total
    return delta_buy, f"BuyVol={vol_buy:.2f} TotalVol={vol_total:.2f}"


def decidir_radar(asset):
    """
    Combina BBW + Volume Delta do ativo na árvore de decisão A/B/C:

      A) Sniper UP   = Squeeze E delta_buy >= 0.70
      B) Sniper DOWN = Squeeze E delta_buy <= 0.30 (delta_sell >= 0.70)
      C) Malha       = sem Squeeze OU (Squeeze com delta entre 0.31 e 0.69)

    Retorna:
      dict com decisao, bbw_atual, bbw_percentil, squeeze, delta_buy, diag.
    """
    bbw, perc, squeeze, erro_bbw = calcular_bbw(asset)
    if bbw is None:
        return {
            "decisao": "MALHA",   # fallback seguro: opera ambos
            "bbw_atual": 0.0, "bbw_percentil": 0.0, "squeeze": False,
            "delta_buy": 0.5,
            "diagnostico": f"BBW indisponível ({erro_bbw}) → fallback MALHA",
        }

    delta, erro_delta = calcular_volume_delta(asset)
    if delta is None:
        return {
            "decisao": "MALHA",   # fallback seguro
            "bbw_atual": bbw, "bbw_percentil": perc, "squeeze": bool(squeeze),
            "delta_buy": 0.5,
            "diagnostico": f"Delta indisponível ({erro_delta}) → fallback MALHA",
        }

    # ── Árvore de decisão ─────────────────────────────────────
    if squeeze and delta >= DELTA_THRESHOLD:
        decisao = "SNIPER_UP"
    elif squeeze and delta <= (1.0 - DELTA_THRESHOLD):
        decisao = "SNIPER_DOWN"
    else:
        decisao = "MALHA"

    diag = (f"BBW={bbw:.5f} (perc={perc:.0f}%, "
            f"squeeze={'SIM' if squeeze else 'NÃO'}) | "
            f"Delta_Buy={delta*100:.1f}% / Delta_Sell={(1-delta)*100:.1f}%")

    return {
        "decisao":       decisao,
        "bbw_atual":     bbw,
        "bbw_percentil": perc,
        "squeeze":       bool(squeeze),
        "delta_buy":     delta,
        "diagnostico":   diag,
    }


# ── Histórico para estratégia FILTER (DSoma_140-165-200 → Multi_2v_REVERSE) ──
_hist_lock = threading.RLock()
_hist_dirs = {"BTC": [0, 0], "ETH": [0, 0], "SOL": [0, 0]}  # [prev1, prev2]
_hist_deltas   = {"BTC": 50.0, "ETH": 50.0, "SOL": 50.0}
_hist_bbw_perc = {"BTC": 50.0, "ETH": 50.0, "SOL": 50.0}  # bbw_perc p/ filtro BBW_30       # delta% do radar anterior

def decidir_estrategia(asset, deltas_atuais):
    """
    Estratégia: E4+Base1.1 + Ind1.2 + BBWalto
    ===========================================
    Simulador: WR=62.7% | PnL=+$65 | PF=1.68 | MaxDD=-$7.50 | p=0.006 | WF=5/5 | Trades=102

    PARÂMETROS:
      DELTA_IND_LO = 120   ← piso do intervalo delta
      DELTA_IND_HI = 154   ← teto do intervalo delta
      BBW_EXPANSAO = 46    ← BBW% médio mínimo (mercado mais expansivo)
      DIFF_MIN     = 5     ← |soma_buy - soma_sell| mínima (sinal não-ambíguo)

    LÓGICA EM 3 CAMADAS:

    [1] GATE — E4 (quando considera entrar):
        Maioria dos ativos na mesma direção na última vela.
        2X1 ou 3X0 → gate abre.
        Empate → ignora completamente.

    [2] FILTROS (qualidade do momento):
        BBW% médio ≥ 46 → mercado em expansão forte.
        DIFF_MIN: |soma_buy - soma_sell| ≥ 5 → sinal não-ambíguo.
          Se buy e sell estiverem muito próximos (diff < 5) → ignora.

    [3] DIREÇÃO — Base1.1 (delta dentro OU fora do intervalo):
        ► Se soma_buy E soma_sell ambas em [120, 154] (intervalo equilibrado):
            Direção pelo delta → buy > sell = UP | sell > buy = DOWN
        ► Se delta FORA do intervalo (pressão extrema de um lado):
            Direção pelo consenso E4 → maioria das velas determina lado
            Ex: 2 verdes 1 vermelha + delta fora → segue as 2 verdes (UP)
            Ex: 3 vermelhas + delta fora → segue as 3 vermelhas (DOWN)

        Diferença vs âncora original:
          Antes: fora do intervalo → SEM_SINAL (ignora)
          Agora: fora do intervalo → usa consenso das velas (E4)
    """
    # ── Lê estado atual ──────────────────────────────────────────
    with _hist_lock:
        dir_btc_1 = _hist_dirs["BTC"][0]    # direção última vela BTC
        dir_eth_1 = _hist_dirs["ETH"][0]    # direção última vela ETH
        dir_sol_1 = _hist_dirs["SOL"][0]    # direção última vela SOL
        bbw_btc   = _hist_bbw_perc.get("BTC", 0.0)
        bbw_eth   = _hist_bbw_perc.get("ETH", 0.0)
        bbw_sol   = _hist_bbw_perc.get("SOL", 0.0)

    # ── Parâmetros ────────────────────────────────────────────────
    DELTA_LO = 120
    DELTA_HI = 154
    BBW_MIN  = 46
    DIFF_MIN = 5

    # ── [1] GATE E4: maioria das velas na mesma direção ──────────
    up1 = sum(1 for d in [dir_btc_1, dir_eth_1, dir_sol_1] if d ==  1)
    dn1 = sum(1 for d in [dir_btc_1, dir_eth_1, dir_sol_1] if d == -1)

    gate_up   = up1 >= 2 and up1 > dn1
    gate_down = dn1 >= 2 and dn1 > up1

    if not gate_up and not gate_down:
        return "SEM_SINAL"   # empate ou sem dados → ignora

    # ── [2a] FILTRO BBW: mercado em expansão forte ───────────────
    bbw_medio = (bbw_btc + bbw_eth + bbw_sol) / 3
    if bbw_medio < BBW_MIN:
        log(f"[{ts()}] ⏭️  [{asset}] BBW médio={bbw_medio:.1f}% < {BBW_MIN}% "
            f"→ mercado comprimido, sem sinal")
        return "SEM_SINAL"

    # ── Calcula delta ─────────────────────────────────────────────
    d_btc = deltas_atuais.get("BTC", 50.0)
    d_eth = deltas_atuais.get("ETH", 50.0)
    d_sol = deltas_atuais.get("SOL", 50.0)

    soma_buy  = d_btc + d_eth + d_sol
    soma_sell = 300.0 - soma_buy
    diff      = abs(soma_buy - soma_sell)

    # ── [2b] FILTRO DIFF_MIN: sinal não-ambíguo ───────────────────
    if diff < DIFF_MIN:
        log(f"[{ts()}] ⏭️  [{asset}] diff={diff:.1f} < {DIFF_MIN} "
            f"→ sinal ambíguo, sem sinal")
        return "SEM_SINAL"

    # ── [3] DIREÇÃO — Base1.1 ────────────────────────────────────
    buy_ok  = DELTA_LO <= soma_buy  <= DELTA_HI
    sell_ok = DELTA_LO <= soma_sell <= DELTA_HI

    if buy_ok and sell_ok:
        # Dentro do intervalo → direção pelo delta (igual à âncora)
        if soma_buy == soma_sell:
            return "SEM_SINAL"
        direcao = "SNIPER_UP"   if soma_buy > soma_sell else "SNIPER_DOWN"
        lado    = "UP"          if soma_buy > soma_sell else "DOWN"
        fonte   = "delta"
    else:
        # Fora do intervalo → direção pelo consenso E4 (Base1.1)
        direcao = "SNIPER_UP"   if gate_up else "SNIPER_DOWN"
        lado    = "UP"          if gate_up else "DOWN"
        fonte   = "consenso E4"

    log(f"[{ts()}] ✅ [SINAL/{asset}] E4={up1}X{dn1} | "
        f"BBW={bbw_medio:.1f}% | "
        f"Δbuy={soma_buy:.0f} Δsell={soma_sell:.0f} diff={diff:.0f} "
        f"→ {lado} [{fonte}]")

    return direcao

def _gravar_radar_csv(ciclo_ts, radar_dict, vela_dict):
    """Grava uma linha por ativo no radar_velas.csv"""
    from datetime import datetime as _dt
    vela_str = _dt.fromtimestamp(ciclo_ts).strftime("%Y-%m-%d %H:%M")
    with csv_lock:
        novo = not Path(RADAR_CSV).exists()
        with open(RADAR_CSV, 'a', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            if novo:
                w.writerow(RADAR_CSV_HDR)
            for asset in ["BTC", "ETH", "SOL"]:
                r = radar_dict.get(asset)
                v = vela_dict.get(asset)
                if not r or not v:
                    continue
                w.writerow([
                        vela_str, asset,
                        r["bbw"], r["bbw_perc"], r["squeeze"],
                        r["delta_buy"], r["delta_sell"], r["decisao"],
                        v["dir"], v["open"], v["high"], v["low"],
                        v["close"], v["var_pct"],
                    ])

def coordinator_radar():
    """
    Loop dedicado: roda em thread separada.
    No segundo RADAR_T_SEG (890 = T-10s) calcula a decisão INDEPENDENTE
    para cada ativo (BTC, ETH, SOL) para a PRÓXIMA vela.
    Cada ativo é aprovado/reprovado pelo seu próprio gráfico.
    """
    log(f"[{ts()}] 🧭 [RADAR] Coordenador iniciado "
        f"(T-{900-RADAR_T_SEG}s da vela, radar independente por ativo).")
    ultimo_ciclo_processado = 0
    _resumo_vela_ciclo = 0
    while True:
        try:
            time.sleep(0.25)
            if state["status"] != "ATIVO":
                continue
            now_ts    = time.time()
            now_ciclo = int(now_ts) // 900 * 900
            seg_vela  = now_ts - now_ciclo

# ── Resumo da vela (T-2s) — roda na thread leve do coordinator ──
            if seg_vela >= 898 and _resumo_vela_ciclo != now_ciclo:
                _resumo_vela_ciclo = now_ciclo
                _vela_csv_dict = {}
                for _rv_asset in ["BTC", "ETH", "SOL"]:
                    try:
                        _rv_df = ws_get_dataframe(_rv_asset)
                        if _rv_df is not None and len(_rv_df) >= 1:
                            _rv_bar = _rv_df.iloc[-1]
                            _rv_op  = float(_rv_bar["open"])
                            _rv_cl  = float(_rv_bar["close"])
                            _rv_pct = ((_rv_cl / _rv_op) - 1) * 100 if _rv_op > 0 else 0
                            _rv_emo = "🟢" if _rv_cl > _rv_op else ("🔴" if _rv_cl < _rv_op else "⚪")
                            _rv_tag = "POSITIVA" if _rv_cl > _rv_op else ("NEGATIVA" if _rv_cl < _rv_op else "NEUTRA")
                            log(f"[{ts()}] {_rv_emo} [VELA {_rv_asset}] {_rv_tag} | "
                                f"Open={_rv_op:.2f} → Close={_rv_cl:.2f} | "
                                f"Var={_rv_pct:+.4f}%")
                            # Atualiza histórico de direções para estratégia
                            _rv_dir_num = 1 if _rv_cl > _rv_op else (-1 if _rv_cl < _rv_op else 0)
                            with _hist_lock:
                                _hist_dirs[_rv_asset] = [_rv_dir_num, _hist_dirs[_rv_asset][0]]

                            _rv_hi = float(_rv_bar["high"])
                            _rv_lo = float(_rv_bar["low"])
                            _vela_csv_dict[_rv_asset] = {
                                "dir": "UP" if _rv_cl > _rv_op else (
                                       "DOWN" if _rv_cl < _rv_op else "FLAT"),
                                "open": round(_rv_op, 2),
                                "high": round(_rv_hi, 2),
                                "low": round(_rv_lo, 2),
                                "close": round(_rv_cl, 2),
                                "var_pct": round(_rv_pct, 4),
                            }
                    except Exception:
                        pass
                # Grava CSV combinando radar (buffer) + resultado da vela
                if now_ciclo in _radar_csv_buffer and _vela_csv_dict:
                    try:
                        _gravar_radar_csv(now_ciclo, _radar_csv_buffer[now_ciclo], _vela_csv_dict)
                    except Exception as _csv_e:
                        log(f"[{ts()}] ⚠️ [CSV] Erro gravando radar_velas: {_csv_e}")
                    # Limpa buffer antigo (mantém só últimos 3 ciclos)
                    _ciclos_antigos = [k for k in _radar_csv_buffer if k < now_ciclo - 2700]
                    for _ck in _ciclos_antigos:
                        _radar_csv_buffer.pop(_ck, None)
            if seg_vela < RADAR_T_SEG:
                continue
            if now_ciclo == ultimo_ciclo_processado:
                continue

            ciclo_alvo = now_ciclo + 900
            hora_alvo  = datetime.fromtimestamp(ciclo_alvo).strftime("%H:%M")
            t0 = time.time()

            log(f"\n[{ts()}] 🧭 [RADAR] ══════════ Vela {hora_alvo} — Radar Independente ══════════")

            # PASSE 1: calcula radar dos 3 ativos (coleta deltas atuais)
            _radares = {}
            _deltas_atuais = {}
            for asset in ["BTC", "ETH", "SOL"]:
                r = decidir_radar(asset)
                _radares[asset] = r
                _deltas_atuais[asset] = round(r["delta_buy"] * 100, 1)
                with _hist_lock:
                    _hist_bbw_perc[asset] = r.get("bbw_percentil", 50.0)

            # PASSE 2: decide estratégia usando deltas ATUAIS dos 3 ativos
            # 2a) Calcula sinal individual de cada ativo
            _decisoes = {}
            for asset in ["BTC", "ETH", "SOL"]:
                _decisoes[asset] = decidir_estrategia(asset, _deltas_atuais)

            for asset in ["BTC", "ETH", "SOL"]:
                r = _radares[asset]
                r["decisao"] = _decisoes[asset]

                # Armazena delta atual
                with _hist_lock:
                    _hist_deltas[asset] = _deltas_atuais[asset]

                with sinal_lock:
                    sinal_radar[asset]["ciclo_alvo"]    = ciclo_alvo
                    sinal_radar[asset]["decisao"]       = r["decisao"]
                    sinal_radar[asset]["bbw_atual"]     = r["bbw_atual"]
                    sinal_radar[asset]["bbw_percentil"] = r["bbw_percentil"]
                    sinal_radar[asset]["squeeze"]       = r["squeeze"]
                    sinal_radar[asset]["delta_buy"]     = r["delta_buy"]
                    sinal_radar[asset]["calculado_em"]  = time.time()
                    sinal_radar[asset]["diagnostico"]   = r["diagnostico"]

                with state_lock:
                    state["radar_por_ativo"][asset] = {
                        "decisao":  r["decisao"],
                        "bbw":      r["bbw_atual"],
                        "bbw_perc": r["bbw_percentil"],
                        "delta":    r["delta_buy"],
                        "squeeze":  r["squeeze"],
                    }
                    if r["decisao"] == "SNIPER_UP":     state["diag_sniper_up"]   += 1
                    elif r["decisao"] == "SNIPER_DOWN": state["diag_sniper_down"] += 1
                    else:                               state["diag_malha"]       += 1

                tag = {
                    "SNIPER_UP":   "🎯 SNIPER UP",
                    "SNIPER_DOWN": "🎯 SNIPER DOWN",
                    "MALHA":       "🕸️  MALHA",
                    "SEM_SINAL":   "⏭️  SEM SINAL",
                }[r["decisao"]]

                # Info da estratégia FILTER
                with _hist_lock:
                    _p1d = _hist_dirs[asset][0]
                    _p2d = _hist_dirs[asset][1]
                _dir_info = (f"Prev2v=[{'↑' if _p2d==1 else '↓' if _p2d==-1 else '?'},"
                             f"{'↑' if _p1d==1 else '↓' if _p1d==-1 else '?'}]")
                _cross_info = f"CrossΔ=[B:{_deltas_atuais.get('BTC',50):.0f} E:{_deltas_atuais.get('ETH',50):.0f} S:{_deltas_atuais.get('SOL',50):.0f}]"
                log(f"[{ts()}] 🧭 [RADAR {asset}] {tag} | {r['diagnostico']} | {_dir_info} {_cross_info}")

                # Buffer para CSV (será combinado com resultado da vela)
                try:
                    if ciclo_alvo not in _radar_csv_buffer:
                        _radar_csv_buffer[ciclo_alvo] = {}
                    _radar_csv_buffer[ciclo_alvo][asset] = {
                        "bbw": round(r["bbw_atual"], 5),
                        "bbw_perc": round(r["bbw_percentil"], 0),
                        "squeeze": 1 if r["squeeze"] else 0,
                        "delta_buy": round(r["delta_buy"] * 100, 1),
                        "delta_sell": round((1 - r["delta_buy"]) * 100, 1),
                        "decisao": r["decisao"],
                    }
                except Exception as _csv_buf_e:
                    log(f"[{ts()}] ⚠️ [CSV] Buffer radar: {_csv_buf_e}")

            elapsed_ms = (time.time() - t0) * 1000
            ultimo_ciclo_processado = now_ciclo
            log(f"[{ts()}] 🧭 [RADAR] ══ 3 ativos calculados ({elapsed_ms:.0f}ms) ══\n")

        except Exception as e:
            log(f"[{ts()}] 💥 [RADAR] Coordenador: {e}")
            time.sleep(1.0)

# ══════════════════════════════════════════════════════════════
# KILL SWITCH — Cenário 2 (Violino Duplo)
# ══════════════════════════════════════════════════════════════
# Disparado quando a Malha de Guerra estava ligada (ambos lados
# postados) E um dos seguros (P4 ou D4) PREENCHEU. A semântica:
#
#   P4 fill = mercado caiu o bastante p/ acionar P3, depois caiu
#             MAIS e tocou em $0.75 do token DOWN (hedge cheio).
#             Conclusão: viés DOWN forte. Não queremos D1/D2/D3
#             vivas — se o mercado revirar e elas preencherem,
#             dobramos exposição contra. Cancelar D1/D2/D3 e
#             ativar D4 como rede de captura caso o mercado
#             volte forte pra cima.
#
#   D4 fill = espelho. Mercado subiu até P4-equivalente, ativou
#             D4 (hedge UP). Cancela P1/P2/P3 vivas, ativa P4.
#
# Sniper (decisao != MALHA) NÃO dispara Kill Switch — só o
# lado correspondente está vivo, não há ordens cruzadas pra
# cancelar.
#
# Idempotência: cada chamada protege com `kill_switch_acionado`
# (set por chave única ciclo+asset+lado), então se P4 fill chegar
# em dois polls consecutivos antes do `slot["filled"]` virar True,
# não dispara duas vezes.

kill_switch_lock = threading.RLock()
kill_switch_acionado = set()  # chaves: f"{asset}_{ciclo_alvo}_{P4|D4}"


def kill_switch_p4(asset, decisao, slots_d, tid_up, mk_up,
                   mct_ciclo, ciclo_alvo):
    """
    P4 PREENCHEU (LADO UP foi até o fim do hedge).
    Args:
      asset       : 'BTC' | 'ETH' | 'SOL'
      decisao     : 'SNIPER_UP' | 'SNIPER_DOWN' | 'MALHA'
      slots_d     : [D1, D2, D3, D4] — slots do worker (passa por referência)
      tid_up      : token_id do UP (D4 compra UP)
      mk_up       : dict de mercado UP (p/ question/close_ts)
      mct_ciclo   : market_close_ts da vela alvo
      ciclo_alvo  : ciclo_ts da vela em que P4 preencheu
    """
    with kill_switch_lock:
        chave = f"{asset}_{ciclo_alvo}_P4"
        if chave in kill_switch_acionado:
            return   # já disparado — idempotente
        kill_switch_acionado.add(chave)

    # ── Sniper: nada a fazer (lado D nem foi postado) ────────
    if decisao != "MALHA":
        log(f"[{ts()}] ℹ️  [{asset}] P4 fill em modo {decisao} — "
            f"Kill Switch NÃO dispara (lado D não foi postado).")
        return

    log(f"\n[{ts()}] 🚨 [KILL SWITCH ACIONADO] [{asset}] ════════════")
    log(f"[{ts()}] 🚨 P4 preenchida → cancelando D1/D2/D3 vivas e "
        f"ativando D4 como rede de captura.")
    log(f"[{ts()}] 🚨 ════════════════════════════════════════════\n")

    D1, D2, D3, D4 = slots_d

    # ── 1) Cancela D1/D2/D3 vivas (não preenchidas) ──────────
    cancelados = []
    for slot in (D1, D2, D3):
        if slot["sent"] and slot["oid"] and not slot["filled"]:
            ok = cancel_order(slot["oid"],
                              label=f"KILLSW_P4→{slot['label']}_{asset}")
            if ok:
                cancelados.append(slot["label"])
                slot["sent"]   = False  # neutraliza p/ não ser checada de novo
                slot["filled"] = False
                slot["oid"]    = None

    log(f"[{ts()}] 🗑️  [KILL SWITCH] [{asset}] Canceladas: "
        f"{', '.join(cancelados) if cancelados else 'nenhuma (já preenchidas/canceladas)'}")

    log(f"[{ts()}] 🔫 [KILL SWITCH] [{asset}] SENTINELA D4 ATIVADO | "
        f"Aguarda preço token UP >= ${SENTINELA_PRECO:.3f} p/ disparar "
        f"{D4_COTAS}c UP @ mercado.")

    with state_lock:
        state["diag_kill_switch_up"] += 1
        state["assimetria_status"][asset] = "SENTINELA_D4_ATIVO"
    log_event("scan", f"🚨 KILL SWITCH UP {asset} | D1/D2/D3 canceladas, SENTINELA D4")

    return "ATIVAR_D4"

def kill_switch_d4(asset, decisao, slots_p, tid_down, mk_down,
                   mct_ciclo, ciclo_alvo):
    """
    D4 PREENCHEU (LADO DOWN foi até o fim do hedge).
    Espelho exato de kill_switch_p4. Cancela P1/P2/P3 vivas e
    ativa P4 (LIMIT BUY 20c DOWN @ $0.75).
    """
    with kill_switch_lock:
        chave = f"{asset}_{ciclo_alvo}_D4"
        if chave in kill_switch_acionado:
            return
        kill_switch_acionado.add(chave)

    if decisao != "MALHA":
        log(f"[{ts()}] ℹ️  [{asset}] D4 fill em modo {decisao} — "
            f"Kill Switch NÃO dispara (lado P não foi postado).")
        return

    log(f"\n[{ts()}] 🚨 [KILL SWITCH ACIONADO] [{asset}] ════════════")
    log(f"[{ts()}] 🚨 D4 preenchida → cancelando P1/P2/P3 vivas e "
        f"ativando P4 como rede de captura.")
    log(f"[{ts()}] 🚨 ════════════════════════════════════════════\n")

    P1, P2, P3, P4 = slots_p

    cancelados = []
    for slot in (P1, P2, P3):
        if slot["sent"] and slot["oid"] and not slot["filled"]:
            ok = cancel_order(slot["oid"],
                              label=f"KILLSW_D4→{slot['label']}_{asset}")
            if ok:
                cancelados.append(slot["label"])
                slot["sent"]   = False
                slot["filled"] = False
                slot["oid"]    = None

    log(f"[{ts()}] 🗑️  [KILL SWITCH] [{asset}] Canceladas: "
        f"{', '.join(cancelados) if cancelados else 'nenhuma (já preenchidas/canceladas)'}")

    log(f"[{ts()}] 🔫 [KILL SWITCH] [{asset}] SENTINELA P4 ATIVADO | "
        f"Aguarda preço token DOWN >= ${SENTINELA_PRECO:.3f} p/ disparar "
        f"{P4_COTAS}c DOWN @ mercado.")

    with state_lock:
        state["diag_kill_switch_dn"] += 1
        state["assimetria_status"][asset] = "SENTINELA_P4_ATIVO"
    log_event("scan", f"🚨 KILL SWITCH DN {asset} | P1/P2/P3 canceladas, SENTINELA P4")

    return "ATIVAR_P4"
            # ══════════════════════════════════════════════════════════════
# WORKER ASSIMETRIA — Escada de Resgate (Laddering) por Ativo
# ══════════════════════════════════════════════════════════════
def worker_condor(asset):
    """
    Worker CONDOR BIDIRECIONAL v3.0
    ═══════════════════════════════
    Por vela 15m, dispara até 8 ordens (4 P + 4 D) conforme
    decisão do Radar BTC (calculada em coordinator_radar aos T-10s):

      SNIPER_UP   → posta P1, P2, P3            (3 ordens)
      SNIPER_DOWN → posta D1, D2, D3            (3 ordens)
      MALHA       → posta P1, P2, P3, D1, D2, D3 (6 ordens)

    Postagem ocorre no T-5s (seg 895) da vela ANTERIOR, no token
    da vela seguinte (graças ao pré-fetch). P4/D4 são condicionais:

      P2 fill → posta P4 (LIMIT BUY 33c DOWN @ $0.87)
      D2 fill → posta D4 (LIMIT BUY 33c UP   @ $0.87)

    Kill Switch fica em função separada — esse worker apenas
    SINALIZA via `kill_switch_request` quando P4 ou D4 preenchem.
    """
    log(f"[{ts()}] ⚡ [CONDOR] Worker {asset} iniciado | "
        f"Lado P: {P1_COTAS}/{P2_COTAS}/{P3_COTAS}c "
        f"@ ${P1_PRECO}/${P2_PRECO}/${P3_PRECO} | "
        f"Lado D: {D1_COTAS}/{D2_COTAS}/{D3_COTAS}c "
        f"@ ${D1_PRECO}/${D2_PRECO}/${D3_PRECO}")

    # ── Estado por ciclo ─────────────────────────────────────
    ciclo_ts   = 0
    ciclo_alvo = 0          # timestamp da vela ALVO (definido na postagem, nunca muda)
    decisao    = None       # 'SNIPER_UP' | 'SNIPER_DOWN' | 'MALHA'
    posto      = False      # já postou as ordens base do T-5s?
    posted_for_ciclo = 0    # ciclo_ts pra qual já postou (evita duplicata E permite próximo)
    ciclo_pulado = False    # sem decisão p/ esse ciclo
    tid_up = None;   tid_down = None
    mk_up  = None;   mk_down  = None
    mct_ciclo = None

    # ── Slots de ordens (8 slots) ────────────────────────────
    # Cada slot é um dict: {oid, sent, filled, fill_price, label, token_id}
    def _slot(label):
        return {"oid": None, "sent": False, "filled": False,
                "fill_price": 0.0, "label": label, "token_id": None}
    P1 = _slot("P1"); P2 = _slot("P2"); P3 = _slot("P3")
    D1 = _slot("D1"); D2 = _slot("D2"); D3 = _slot("D3")

    # ── Pré-fetch silencioso ─────────────────────────────────
    _pf_up = None; _pf_down = None; _pf_done = False
    _preservar_reset = False   # True = ordens postadas em T-5s aguardam a virada
    _resumo_vela_feito = False  # log de abertura/fechamento da vela no T-2s
    _p1_cancelou_d = False      # P1 filled → D2/D3/D4 cancelados
    _d1_cancelou_p = False      # D1 filled → P2/P3/P4 cancelados
    _force_post = False         # força postagem imediata (bypass seg_vela >= 899)

    while True:
        try:
            time.sleep(POLL_FILL_INTERVAL)

            if state["status"] != "ATIVO":
                continue

            now_ts    = time.time()
            now_ciclo = int(now_ts) // 900 * 900
            seg_vela  = now_ts - now_ciclo

            # ══════════════════════════════════════════════════
            # RESET — Nova vela 15m
            # ══════════════════════════════════════════════════
            if now_ciclo != ciclo_ts:
                if _preservar_reset:
                    # ── Ordens T-5s são para ESTA vela → preservar ──
                    # Só avança o ciclo e limpa pré-fetch.
                    # Slots, decisão, tokens e mk_* sobrevivem intactos.
                    _preservar_reset = False
                    ciclo_ts = now_ciclo
                    _pf_up = None; _pf_down = None; _pf_done = False
                    with state_lock:
                        state["assimetria_status"][asset] = (
                            f"{decisao} MONITORANDO")
                    _resumo_vela_feito = False
                    log(f"[{ts()}] 🔄 [{asset}] RESET SUAVE — "
                        f"ordens T-5s preservadas para vela alvo.")
                else:
                    # ── Reset normal — cancela ordens da vela anterior ──
                    for slot in (P1, P2, P3, D1, D2, D3):
                        if slot["sent"] and slot["oid"] and not slot["filled"]:
                            cancel_order(slot["oid"],
                                         label=f"RESET_{slot['label']}_{asset}")

                    ciclo_ts     = now_ciclo
                    ciclo_alvo   = 0
                    posted_for_ciclo = 0
                    decisao      = None
                    posto        = False
                    ciclo_pulado = False
                    tid_up    = None;   tid_down = None
                    mk_up     = None;   mk_down  = None
                    mct_ciclo = None
                    P1 = _slot("P1"); P2 = _slot("P2"); P3 = _slot("P3")
                    D1 = _slot("D1"); D2 = _slot("D2"); D3 = _slot("D3")
                    _resumo_vela_feito  = False
                    _p1_cancelou_d = False
                    _d1_cancelou_p = False
                    _force_post = False

                    if _pf_up and _pf_down:
                        mk_up   = _pf_up
                        mk_down = _pf_down
                        tid_up    = mk_up["token_id"]
                        tid_down  = mk_down["token_id"]
                        mct_ciclo = mk_up["market_close_ts"]
                    _pf_up = None; _pf_down = None; _pf_done = False

                    with state_lock:
                        state["assimetria_status"][asset] = "AGUARDANDO_RADAR"
                        state["diag_velas"] += 1

                    # ── Post imediato se radar já decidiu pra esta vela ──
                    with sinal_lock:
                        _ri_alvo = sinal_radar[asset]["ciclo_alvo"]
                        _ri_dec  = sinal_radar[asset]["decisao"]
                    if _ri_alvo == now_ciclo and _ri_dec and _ri_dec != "SEM_SINAL":
                        log(f"[{ts()}] ⚡ [{asset}] RESET detectou sinal pronto "
                            f"({_ri_dec}) → forçando postagem imediata.")
                        posted_for_ciclo = 0
                        ciclo_pulado = False
                        posto = False
                        _force_post = True

            # ── Zona crítica (silêncio de radar) ──────────────
            _zona_critica = (seg_vela <= 10.0) or (
                mct_ciclo is not None and (mct_ciclo - now_ts) <= 15.0)

            # ══════════════════════════════════════════════════
            # PRÉ-FETCH SILENCIOSO — Últimos 10s da vela atual
            # (busca AMBOS os tokens do PRÓXIMO ciclo)
            # ══════════════════════════════════════════════════
            if not _pf_done and seg_vela >= 890:
                proximo_ciclo_ts = now_ciclo + 900

                def _buscar_pf(direction):
                    backoffs = [0.1, 0.2, 0.4, 0.8, 1.5]
                    for i, wait in enumerate(backoffs):
                        try:
                            mk = fetch_crypto_market(
                                asset, direction,
                                target_ciclo_ts=proximo_ciclo_ts)
                            if mk: return mk
                        except Exception as e:
                            log(f"[{ts()}] ⚠️ [{asset}] _buscar_pf "
                                f"{i+1}/5 ({direction}): "
                                f"{type(e).__name__}: {e}")
                        time.sleep(wait)
                    return None
                try:
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        fut_u = pool.submit(_buscar_pf, "up")
                        fut_d = pool.submit(_buscar_pf, "down")
                        _pf_up   = fut_u.result(timeout=8)
                        _pf_down = fut_d.result(timeout=8)
                    _pf_done = True
                    ok_u = "✅" if _pf_up   else "❌"
                    ok_d = "✅" if _pf_down else "❌"
                    log(f"[{ts()}] 🔄 [{asset}] PRÉ-FETCH ciclo={proximo_ciclo_ts} | "
                        f"UP={ok_u} DOWN={ok_d}")
                except Exception as e:
                    log(f"[{ts()}] ⚠️ [{asset}] Pré-fetch falhou: "
                        f"{type(e).__name__}: {repr(e)}")
                    _pf_done = True

            # ══════════════════════════════════════════════════
            # POSTAGEM T-5s — Lê decisão do radar e dispara base
            # IMPORTANTE: rodamos POSTAGEM_T_SEG (895) na vela
            # ATUAL, postando ordens no token da vela SEGUINTE.
            # ══════════════════════════════════════════════════
            if (not ciclo_pulado
                    and (seg_vela >= POSTAGEM_T_SEG or _force_post)
                    and posted_for_ciclo != (now_ciclo + 900)):

                # ── 1) Lê o sinal do radar (alvo = ciclo seguinte) ──
                with sinal_lock:
                    sinal_alvo = sinal_radar[asset]["ciclo_alvo"]
                    sinal_dec  = sinal_radar[asset]["decisao"]
                    sinal_diag = sinal_radar[asset]["diagnostico"]

                proximo_ciclo_ts = now_ciclo if _force_post else now_ciclo + 900
                if sinal_alvo != proximo_ciclo_ts:
                    if _force_post and seg_vela < 3:
                        # Coordenador pode ainda não ter gravado — tenta de novo no próximo poll
                        continue
                    log(f"[{ts()}] ⏭️ [{asset}/USDT] SEM SINAL DO RADAR "
                        f"(alvo={sinal_alvo}, esperado={proximo_ciclo_ts}) "
                        f"→ vela pulada.")
                    _force_post = False
                    ciclo_pulado = True; posto = True
                    with state_lock:
                        state["assimetria_status"][asset] = "PULADO_SEM_RADAR"
                    continue

                # ── 2) SEMPRE busca tokens frescos para o ciclo alvo ──
                # mk_up/mk_down podem conter tokens EXPIRADOS da vela
                # anterior (preservados pelo RESET SUAVE). Forçar limpeza.
                mk_up  = None
                mk_down = None
                # Absorve pré-fetch se disponível para este ciclo
                if _pf_up and _pf_down:
                    mk_up   = _pf_up
                    mk_down = _pf_down
                if not (mk_up and mk_down):
                    log(f"[{ts()}] ⚠️ [{asset}/USDT] Pré-fetch indisponível "
                        f"no T-5s — buscando agora...")
                    def _buscar(d):
                        for _ in range(3):
                            mk = fetch_crypto_market(
                                asset, d, target_ciclo_ts=proximo_ciclo_ts)
                            if mk: return mk
                            time.sleep(0.1)
                        return None
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        fu = pool.submit(_buscar, "up")
                        fd = pool.submit(_buscar, "down")
                        mk_up   = fu.result(timeout=6)
                        mk_down = fd.result(timeout=6)

                if not mk_up or not mk_down:
                    log(f"[{ts()}] ❌ [{asset}/USDT] Mercado UP={bool(mk_up)} "
                        f"DOWN={bool(mk_down)} — abortando ciclo.")
                    ciclo_pulado = True; posto = True
                    continue

                tid_up    = mk_up["token_id"]
                tid_down  = mk_down["token_id"]
                mct_ciclo = mk_up["market_close_ts"]
                decisao   = sinal_dec

                # Estratégia sem sinal → pula vela inteira
                if decisao == "SEM_SINAL":
                    ciclo_pulado = True; posto = True
                    posted_for_ciclo = proximo_ciclo_ts
                    with state_lock:
                        state["assimetria_status"][asset] = "SEM_SINAL — aguardando"
                    log(f"[{ts()}] ⏭️ [{asset}/USDT] SEM SINAL → vela pulada, aguardando próximo sinal.")
                    continue

                ciclo_alvo = proximo_ciclo_ts   # vela ALVO — fixo, não muda no RESET SUAVE
                hora_alvo = datetime.fromtimestamp(proximo_ciclo_ts).strftime("%H:%M")

                # Anota tokens nos slots
                P1["token_id"] = tid_up;   P2["token_id"] = tid_up;   P3["token_id"] = tid_up
                D1["token_id"] = tid_down; D2["token_id"] = tid_down; D3["token_id"] = tid_down

                tag = {
                    "SNIPER_UP":   "🎯 SNIPER UP",
                    "SNIPER_DOWN": "🎯 SNIPER DOWN",
                    "MALHA":       "🕸️  MALHA DE GUERRA",
                }[decisao]

                log(f"\n[{ts()}] ⚡ [{asset}/USDT] {'═'*52}")
                log(f"[{ts()}] ⚡ [{asset}/USDT] T-5s | {tag} | vela alvo {hora_alvo}")
                log(f"[{ts()}] ⚡ [{asset}/USDT] {sinal_diag}")
                log(f"[{ts()}] ⚡ [{asset}/USDT] {'═'*52}\n")

                # ── 3) Reseta todos os slots para o novo ciclo ──
                for _s in (P1, P2, P3, D1, D2, D3):
                    _s["oid"]        = None
                    _s["sent"]       = False
                    _s["filled"]     = False
                    _s["fill_price"] = 0.0
                _p1_cancelou_d = False
                _d1_cancelou_p = False

                # ── 4) Define ordens a postar conforme decisão ──
                a_postar = []
                if decisao in ("SNIPER_UP", "MALHA"):
                    a_postar += [
                        (P1, P1_PRECO, P1_COTAS, tid_up,   "[LADO UP] P1"),
                        (P2, P2_PRECO, P2_COTAS, tid_up,   "[LADO UP] P2"),
                        (P3, P3_PRECO, P3_COTAS, tid_up,   "[LADO UP] P3"),
                    ]
                if decisao in ("SNIPER_DOWN", "MALHA"):
                    a_postar += [
                        (D1, D1_PRECO, D1_COTAS, tid_down, "[LADO DN] D1"),
                        (D2, D2_PRECO, D2_COTAS, tid_down, "[LADO DN] D2"),
                        (D3, D3_PRECO, D3_COTAS, tid_down, "[LADO DN] D3"),
                    ]

                # ── 4) Dispara TODAS em paralelo ───────────────
                def _enviar(slot, preco, cotas, tid, label_log):
                    label = f"{slot['label']}_{asset}"
                    resp  = execute_limit_buy(tid, preco, cotas, label)
                    if isinstance(resp, dict) and resp.get("status") == "success":
                        slot["oid"]  = resp.get("orderID")
                    slot["sent"] = True
                    return slot["oid"], label_log

                with ThreadPoolExecutor(max_workers=len(a_postar)) as pool:
                    futs = [pool.submit(_enviar, s, p, c, t, lab)
                            for (s, p, c, t, lab) in a_postar]
                    for f in as_completed(futs):
                        try: f.result(timeout=45)
                        except Exception as e:
                            log(f"[{ts()}] ⚠️ [{asset}] post error: {e}")

                posto = True
                _force_post = False
                _preservar_reset = True    # protege contra RESET na virada de vela
                posted_for_ciclo = proximo_ciclo_ts  # marca QUAL ciclo postou
                with state_lock:
                    state["assimetria_status"][asset] = (
                        f"{decisao} POSTADO ({len(a_postar)} ordens)")

                resumo = " | ".join(
                    f"{s['label']}={'OK' if s['oid'] else 'FAIL'}"
                    for (s, _, _, _, _) in a_postar
                )
                log(f"[{ts()}] ✅ [{asset}/USDT] {len(a_postar)} ordens postadas | {resumo}")
                
            # ══════════════════════════════════════════════════
            # MONITOR DE FILLS — só após postagem e dentro da vela alvo
            # ══════════════════════════════════════════════════
            if posto and not ciclo_pulado and decisao is not None:

                # Helper de fill (REAL ou SIM)
                def _check(slot):
                    if not slot["sent"] or not slot["oid"] or slot["filled"]:
                        return False, 0.0
                    if TRADE_REAL:
                        return check_order_fill(slot["oid"])
                    # SIM: regra unificada (ask <= limit + 0.015)
                    return check_fill_sim(slot["token_id"], _slot_preco(slot))

                # Mapa label→preço (helper local)
                def _slot_preco(slot):
                    return {
                        "P1": P1_PRECO, "P2": P2_PRECO, "P3": P3_PRECO,
                        "D1": D1_PRECO, "D2": D2_PRECO, "D3": D3_PRECO,
                    }[slot["label"]]

                # ── Fills genéricos das ordens base + P4/D4 ──────
                def _processar_fill(slot, side_tag, token_dir,
                                    diag_counter, mk_lookup):
                    """side_tag: 'UP' | 'DOWN'   token_dir: token usado p/ vencimento"""
                    if slot["filled"]:
                        return
                    filled, fp = _check(slot)
                    if not filled:
                        return
                    preco_fill = fp if fp > 0.001 else _slot_preco(slot)
                    slot["filled"]     = True
                    slot["fill_price"] = preco_fill
                    log(f"[{ts()}] 🎯 [{side_tag}] [{asset}] FILL "
                        f"{slot['label']} @ ${preco_fill:.3f} "
                        f"({_slot_preco(slot):.2f} limit)")
                    pk = f"CONDOR_{slot['label']}_{asset}_{ciclo_alvo}"
                    with positions_lock:
                        positions[pk] = {
                            "token_id":        slot["token_id"],
                            "entry_price":     preco_fill,
                            "cotas":           {"P1":P1_COTAS,"P2":P2_COTAS,"P3":P3_COTAS,
                                                "D1":D1_COTAS,"D2":D2_COTAS,"D3":D3_COTAS}[slot["label"]],
                            "question":        mk_lookup["question"],
                            "direction":       token_dir,   # qual token? up/down
                            "phase":           slot["label"],
                            "entry_time":      datetime.now(),
                            "asset":           asset,
                            "market_close_ts": mct_ciclo,
                            "ciclo_ts":        ciclo_alvo,       # vela ALVO (fixo)
                        }
                    with state_lock:
                        state[diag_counter] += 1
                        state["open_positions"] = len(positions)

                # Lado P (compra token UP)
                _processar_fill(P1, "LADO UP", "up",   "diag_p1_fills", mk_up)

                if P1["filled"] and not _p1_cancelou_d and not D1["filled"]:
                    _p1_cancelou_d = True
                    _d1_cancelou_p = True
                    _canc_p1 = []
                    for _sl in (D2, D3):
                        if _sl["sent"] and _sl["oid"] and not _sl["filled"]:
                            cancel_order(_sl["oid"], label=f"P1→{_sl['label']}_{asset}")
                            _canc_p1.append(_sl["label"])
                            _sl["sent"] = False; _sl["filled"] = False; _sl["oid"] = None
                    if _canc_p1:
                        log(f"[{ts()}] ⚔️  [P1 GATILHO] [{asset}] P1 filled → "
                            f"Canceladas lado D: {', '.join(_canc_p1)}")

                # P2 fill
                if not P2["filled"]:
                    _processar_fill(P2, "LADO UP", "up", "diag_p2_fills", mk_up)

                # P3 (fill normal, imediata)
                _processar_fill(P3, "LADO UP", "up", "diag_p3_fills", mk_up)

                # Lado D (compra token DOWN)
                _processar_fill(D1, "LADO DN", "down", "diag_d1_fills", mk_down)

                # D1 filled PRIMEIRO → cancela P2, P3
                if D1["filled"] and not _d1_cancelou_p and not P1["filled"]:
                    _d1_cancelou_p = True
                    _p1_cancelou_d = True
                    _canc_d1 = []
                    for _sl in (P2, P3):
                        if _sl["sent"] and _sl["oid"] and not _sl["filled"]:
                            cancel_order(_sl["oid"], label=f"D1→{_sl['label']}_{asset}")
                            _canc_d1.append(_sl["label"])
                            _sl["sent"] = False; _sl["filled"] = False; _sl["oid"] = None
                    if _canc_d1:
                        log(f"[{ts()}] ⚔️  [D1 GATILHO] [{asset}] D1 filled → "
                            f"Canceladas lado P: {', '.join(_canc_d1)}")

                # D2 fill
                if not D2["filled"]:
                    _processar_fill(D2, "LADO DN", "down", "diag_d2_fills", mk_down)

                # D3 (fill normal, imediata)
                _processar_fill(D3, "LADO DN", "down", "diag_d3_fills", mk_down)

            # ── Radar informativo (fora zona crítica, 1x a cada 30s) ─────
            if not _zona_critica and not posto:
                if int(seg_vela) % 30 == 0 and int(seg_vela) != getattr(
                        worker_condor, f"_last_log_{asset}", -1):
                    setattr(worker_condor, f"_last_log_{asset}", int(seg_vela))
                    try:
                        df = ws_get_dataframe(asset)
                        if df is not None and len(df) >= 5:
                            cl = df["close"].values
                            log(f"[{ts()}] 📊 [CONDOR] {asset}/USDT | "
                                f"Close:{cl[-1]:.2f} | "
                                f"Vela:{seg_vela:.0f}s | "
                                f"Status:{state['assimetria_status'].get(asset,'?')}")
                    except Exception:
                        pass

        except Exception as e:
            import traceback
            log(f"[{ts()}] 💥 [CONDOR] Worker {asset}: {e}")
            log(traceback.format_exc())
            time.sleep(1.0)

            # ══════════════════════════════════════════════════════════════
# FLASK — Dashboard porta 8516
# ══════════════════════════════════════════════════════════════
app = Flask(__name__)

@app.route('/')
def index():
    with state_lock:
        return jsonify(state)

@app.route('/positions')
def get_positions():
    with positions_lock:
        return jsonify({
            "positions": {
                k: {**v, 'entry_time': str(v['entry_time'])}
                for k, v in positions.items()
            }
        })
@app.route('/status')
def get_status():
    with state_lock:
        return jsonify({
            "status":              state["status"],
            "trade_mode":          state["trade_mode"],
            "balance":             round(state["balance"], 2),
            "win_rate":            round(state["win_rate"], 1),
            "trades_count":        state["trades_count"],
            "open_positions":      state["open_positions"],
            "assimetria_status":   state["assimetria_status"],
            "radar_por_ativo":     state["radar_por_ativo"],
            "diag": {
                "velas":           state["diag_velas"],
                "sniper_up":       state["diag_sniper_up"],
                "sniper_down":     state["diag_sniper_down"],
                "malha":           state["diag_malha"],
                "p_fills": {
                    "p1": state["diag_p1_fills"], "p2": state["diag_p2_fills"],
                    "p3": state["diag_p3_fills"],
                },
                "d_fills": {
                    "d1": state["diag_d1_fills"], "d2": state["diag_d2_fills"],
                    "d3": state["diag_d3_fills"],
                },
                "kill_switch_up":   state["diag_kill_switch_up"],
                "kill_switch_dn":   state["diag_kill_switch_dn"],
                "wins":             state["diag_wins"],
                "losses":           state["diag_losses"],
            },
        })

@app.route('/config')
def get_config():
    return jsonify({
        "estrategia": "CONDOR BIDIRECIONAL v3.0",
        "lado_P": {
            "P1": f"{P1_COTAS}c UP @ ${P1_PRECO:.2f} (T-5s)",
            "P2": f"{P2_COTAS}c UP @ ${P2_PRECO:.2f} (T-5s)",
            "P3": f"{P3_COTAS}c UP @ ${P3_PRECO:.2f} (T-5s)",
        },
        "lado_D": {
            "D1": f"{D1_COTAS}c DOWN @ ${D1_PRECO:.2f} (T-5s)",
            "D2": f"{D2_COTAS}c DOWN @ ${D2_PRECO:.2f} (T-5s)",
            "D3": f"{D3_COTAS}c DOWN @ ${D3_PRECO:.2f} (T-5s)",
        },
        "radar": {
            "BBW_PERIODO":            BBW_PERIODO,
            "BBW_SQUEEZE_PERCENTIL":  BBW_SQUEEZE_PERCENTIL,
            "BBW_PERCENTIL_LOOKBACK": BBW_PERCENTIL_LOOKBACK,
            "DELTA_THRESHOLD":        DELTA_THRESHOLD,
            "RADAR_T_SEG":            RADAR_T_SEG,
            "POSTAGEM_T_SEG":         POSTAGEM_T_SEG,
        },
        "QUARENTENA_PNL_S": QUARENTENA_PNL_S,
        "FLASK_PORT":       FLASK_PORT,
        "TRADE_REAL":       TRADE_REAL,
    })

@app.route('/pause')
def pause_bot():
    with state_lock: state["status"] = "PAUSADO"
    return jsonify({"status": "PAUSADO"})

@app.route('/resume')
def resume_bot():
    with state_lock: state["status"] = "ATIVO"
    return jsonify({"status": "ATIVO"})

@app.route('/sinal_radar')
def get_sinal_radar():
    """Diagnóstico do último cálculo do Radar por ativo."""
    with sinal_lock:
        resultado = {}
        for asset in ["BTC", "ETH", "SOL"]:
            sm = dict(sinal_radar[asset])
            sm["ciclo_alvo_hora"] = (
                datetime.fromtimestamp(sm["ciclo_alvo"]).strftime("%H:%M:%S")
                if sm["ciclo_alvo"] else "N/A")
            sm["calculado_em_hora"] = (
                datetime.fromtimestamp(sm["calculado_em"]).strftime("%H:%M:%S")
                if sm["calculado_em"] else "N/A")
            resultado[asset] = sm
    return jsonify(resultado)



    # ══════════════════════════════════════════════════════════════
# STARTUP
# ══════════════════════════════════════════════════════════════
if __name__ == '__main__':
    log("\n" + "═" * 64)
    log("  BOT CONDOR 15 — v3.0 (Máquina de Condor Bidirecional)")
    log(f"  Modo     : {'REAL 🔴' if TRADE_REAL else 'SIMULAÇÃO 🟡'}")
    log(f"  Porta    : {FLASK_PORT}")
    log(f"  Ativos   : BTC / ETH / SOL  (Radar Independente por ativo)")
    log(f"")
    log(f"  ┌─ RADAR INDEPENDENTE (T-{900-RADAR_T_SEG}s, por ativo) ──────────")
    log(f"  │  BBW({BBW_PERIODO})  Squeeze ⇔ percentil ≤ {BBW_SQUEEZE_PERCENTIL}% "
        f"(janela {BBW_PERCENTIL_LOOKBACK})")
    log(f"  │  Volume Delta (vela em formação)")
    log(f"  │    Squeeze + Delta_Buy  ≥ {DELTA_THRESHOLD*100:.0f}%  → SNIPER UP")
    log(f"  │    Squeeze + Delta_Sell ≥ {DELTA_THRESHOLD*100:.0f}%  → SNIPER DOWN")
    log(f"  │    Resto (sem squeeze ou delta misto) → MALHA DE GUERRA")
    log(f"  └────────────────────────────────────────────────────────")
    log(f"")
    log(f"  ┌─ ESCADA (T-{900-POSTAGEM_T_SEG}s — postagem na vela seguinte) ──")
    log(f"  │  Lado P (token UP):")
    log(f"  │    P1: {P1_COTAS:>2}c UP   @ ${P1_PRECO:.2f}    P2: {P2_COTAS:>2}c UP   @ ${P2_PRECO:.2f}    P3: {P3_COTAS:>2}c UP   @ ${P3_PRECO:.2f}")
    log(f"  │  Lado D (token DOWN — espelho):")
    log(f"  │    D1: {D1_COTAS:>2}c DOWN @ ${D1_PRECO:.2f}    D2: {D2_COTAS:>2}c DOWN @ ${D2_PRECO:.2f}    D3: {D3_COTAS:>2}c DOWN @ ${D3_PRECO:.2f}")
    log(f"  └────────────────────────────────────────────────────────")
    log(f"")
    log(f"  Vencimento : Oráculo Binance após quarentena {QUARENTENA_PNL_S:.0f}s")
    log("═" * 64 + "\n")

    # ── Diagnóstico de credenciais ─────────────────────────────
    try:
        w3  = Web3()
        ac  = w3.eth.account.from_key(PRIVATE_KEY)
        log(f"  PRIVATE_KEY : {ac.address[:6]}...{ac.address[-4:]}")
        log(f"  FUNDER      : {FUNDER_ADDRESS[:6]}...{FUNDER_ADDRESS[-4:]}")
        log(f"  Mesmo?      : {ac.address.lower() == FUNDER_ADDRESS.lower()}")
    except Exception as e:
        log(f"  ⚠️  Credenciais: {e}")

    # ── WebSocket Binance ──────────────────────────────────────
    iniciar_ws_manager()
    log("▶ WS Manager Binance 15m iniciado.")

    # ── Monitor de posições (vencimento + oráculo) ─────────────
    threading.Thread(
        target=monitor_positions, daemon=True, name="assim_monitor").start()
    log("▶ Monitor de posições (Oráculo 60s) iniciado.")

    # ── Coordenador do Radar BTC (T-10s da vela) ───────────────
    threading.Thread(
        target=coordinator_radar, daemon=True,
        name="condor_radar").start()
    log(f"▶ Coordenador do Radar Independente iniciado "
        f"(decisão por ativo aos T-{900-RADAR_T_SEG}s).")

    # ── Workers Condor por ativo (BTC / ETH / SOL) ─────────────
    for sym in SYMBOLS:
        asset = sym.split("/")[0]
        t = threading.Thread(
            target=worker_condor, args=(asset,),
            daemon=True, name=f"condor_worker_{asset}")
        t.start()
        time.sleep(0.2)
    log("▶ Workers Condor BTC / ETH / SOL iniciados.")

    # ── Flask ──────────────────────────────────────────────────
    log(f"▶ Dashboard: http://localhost:{FLASK_PORT}")
    log(f"▶ Status:    http://localhost:{FLASK_PORT}/status")
    log(f"▶ Config:    http://localhost:{FLASK_PORT}/config")
    log(f"▶ Radar:     http://localhost:{FLASK_PORT}/sinal_radar\n")
    app.run(host='0.0.0.0', port=FLASK_PORT, debug=False, use_reloader=False)

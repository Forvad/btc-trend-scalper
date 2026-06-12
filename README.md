# BTC Trend Scalper

Трендовый бот для BTC на **Hyperliquid** (perp `BTC/USDC:USDC`): **EMA (20/50) + Supertrend + Volume** с выходом по Supertrend SL или полосам Боллинджера.

## Логика

**Вход LONG:**
- Цена пробивает вверх облако EMA (закрытие выше `max(EMA20, EMA50)` после нахождения ниже)
- Supertrend в бычьем режиме (зелёный)
- Объём текущей свечи выше среднего (SMA 20)

**Выход LONG:**
- **Stop-Loss:** закрытие ниже линии Supertrend
- **Take-Profit:** касание верхней полосы Боллинджера (20, 2)

**Вход SHORT (зеркально):**
- Пробой облака EMA вниз + Supertrend медвежий + объём выше среднего

**Выход SHORT:**
- **Stop-Loss:** закрытие выше линии Supertrend
- **Take-Profit:** касание нижней полосы Боллинджера (20, 2)

## Установка

```bash
cd Projects/btc-trend-scalper
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

## Бэктест

```bash
python main.py backtest -t 15m
python main.py backtest -t 1h
```

## Paper-trading

Симуляция на живых котировках (без реальных ордеров):

```bash
python main.py paper -t 15m
```

## Live-торговля (Hyperliquid)

1. Скопируйте `.env.example` → `.env` и укажите ключи:
   - `HYPERLIQUID_PRIVATE_KEY` — приватный ключ **API wallet** (создаётся в Settings → API)
   - `HYPERLIQUID_WALLET_ADDRESS` — адрес **основного аккаунта** с USDC (тот же, что в UI Hyperliquid при депозите). Это **не** адрес API wallet

   Если в Telegram баланс $0, а в приложении есть средства — почти всегда указан неверный `HYPERLIQUID_WALLET_ADDRESS`.

2. Проверка без ордеров:
```bash
python main.py live -t 15m --dry-run
```

3. Реальная торговля (нужно явное подтверждение):
```bash
python main.py live -t 1h --confirm-live
```

## Telegram-уведомления

В `.env` добавьте:
```env
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=your_chat_id
```

Уведомления приходят при:
- старте бота (paper/live)
- открытии сделки (LONG/SHORT)
- закрытии сделки (PnL, причина)
- любой ошибке (текст + traceback)

Настройки в `config.yaml` → `telegram`:
```yaml
telegram:
  enabled: true
  notify_on_start: true
  notify_on_trade: true
  notify_on_error: true
```

Параметры в `config.yaml` → секция `live`:
- `leverage: 1` — плечо по умолчанию
- `max_notional_usd` — лимит размера позиции
- `slippage` — допуск для market-ордеров

## Конфигурация

Параметры в `config.yaml`:

**Биржа (Hyperliquid perps, tier 0):**
- Maker: 0.015%
- Taker: 0.045%
- Вход: taker (market), стоп: taker, тейк у BB: maker (limit)

**Стратегия:**
- EMA: 20 / 50
- Supertrend: ATR 10, множитель 3.0
- Bollinger: 20, 2σ
- Volume SMA: 20

## Структура

```
src/
  indicators/   # EMA, Supertrend, Bollinger, Volume
  strategy/     # Логика сигналов
  backtest/     # Движок бэктеста
  paper/        # Paper-trading
  data/         # Загрузка OHLCV через ccxt
```

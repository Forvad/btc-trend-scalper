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

   Если в уведомлениях баланс $0, а в приложении есть средства — почти всегда указан неверный `HYPERLIQUID_WALLET_ADDRESS`.

2. Проверка без ордеров:
```bash
python main.py live -t 15m --dry-run
```

3. Реальная торговля (нужно явное подтверждение):
```bash
python main.py live -t 1h --confirm-live
```

## Docker (VPS и локально)

Бот можно запустить в контейнере — удобно для VPS: автоперезапуск, логи на диске, секреты в `.env`.

Подробный гайд: [DOCKER.md](DOCKER.md)

### Требования

- Docker и Docker Compose v2
- Файлы `.env` и `config.yaml` в корне проекта

### Быстрый старт

```bash
git clone https://github.com/Forvad/btc-trend-scalper.git
cd btc-trend-scalper
cp .env.example .env
nano .env          # ключи Hyperliquid + NTFY_TOPIC
chmod 600 .env
```

Заполните `.env`:

```env
HYPERLIQUID_PRIVATE_KEY=0x...
HYPERLIQUID_WALLET_ADDRESS=0x...
NTFY_TOPIC=ваш_логин_из_приложения_ntfy
```

**Dry-run** (без ордеров):

```bash
docker compose build
docker compose --profile dry up -d bot-dry
docker compose logs -f bot-dry
```

**Live:**

```bash
docker compose down
docker compose up -d bot
docker compose logs -f bot
```

Логи на хосте: `./logs/bot_YYYY-MM-DD.log`

Таймфрейм и режим — в `docker-compose.yml`, поле `command`:

```yaml
command: ["live", "-t", "1h", "--confirm-live", "-c", "config.yaml"]
```

### Полезные команды

| Действие | Команда |
|----------|---------|
| Статус | `docker compose ps` |
| Перезапуск | `docker compose restart bot` |
| Остановка | `docker compose stop bot` |
| Бэктест разово | `docker compose --profile tools run --rm backtest` |
| Обновление | `git pull && docker compose build && docker compose up -d bot` |

`config.yaml` монтируется в контейнер — после правок достаточно `docker compose restart bot` (пересборка не нужна).

### Установка Docker на Ubuntu (VPS)

```bash
apt update && apt install -y ca-certificates curl
curl -fsSL https://get.docker.com | sh
systemctl enable docker && systemctl start docker
```

## Уведомления (ntfy.sh)

В `.env`:

```env
NTFY_TOPIC=ваш_логин_из_приложения_ntfy
```

Топик = логин в [приложении ntfy](https://ntfy.sh/app). Подпишитесь на этот топик, чтобы получать push.

Уведомления приходят при:
- старте бота (paper/live)
- открытии сделки (LONG/SHORT)
- закрытии сделки (PnL, причина)
- любой ошибке (текст + traceback)

Настройки в `config.yaml` → `notifications`:

```yaml
notifications:
  enabled: true
  notify_on_start: true
  notify_on_trade: true
  notify_on_error: true
```

Параметры в `config.yaml` → секция `live`:
- `leverage` — плечо на бирже
- `use_leverage_for_sizing` — учитывать плечо в размере ордера
- `position_size_pct` — доля buying power на сделку (0.95 = 95%)
- `max_notional_usd` — потолок номинала позиции в USD
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
  live/         # Live-торговля на Hyperliquid
  notifications/# ntfy.sh
  data/         # Загрузка OHLCV через ccxt
Dockerfile
docker-compose.yml
DOCKER.md       # Полная инструкция по VPS
```

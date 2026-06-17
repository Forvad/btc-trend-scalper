# Конфиги по монетам

Каждая монета — отдельный YAML. **HYPE** остаётся в корневом `config.yaml` (и дубликат здесь).

| Файл | Символ | Базовая стратегия (1h) | Live-like 1h* |
|------|--------|------------------------|---------------|
| `config-hype.yaml` | HYPE/USDC:USDC | EMA 9/21, ST 10×2.5, BB 20/2.5 | проверен в live |
| `config-btc.yaml` | BTC/USDC:USDC | EMA 20/50, ST 10×3.0, BB 20/2.5 | консервативный† |
| `config-eth.yaml` | ETH/USDC:USDC | EMA 9/21, ST 10×4.0, BB 20/2.5 | **+3.9%** |
| `config-sui.yaml` | SUI/USDC:USDC | EMA 9/21, ST 7×2.5 → 1h ST 10×3.5 | **+3.8%** (1h) |
| `config-zec.yaml` | ZEC/USDC:USDC | EMA 12/26, ST 7×2.5, BB 20/2.5 | **+27.3%** (1h live) |

\* Бэктест `live_like` + 5m intrabar, ~1000 свечей 1h.  
† Агрессивный fast-grid для BTC на live_like давал минус; выбраны более медленные EMA 20/50.

## Запуск

```bash
# Бэктест
python main.py backtest -c configs/config-btc.yaml -t 1h
python main.py backtest -c configs/config-eth.yaml -t 1h --max

# Live (один бот = один конфиг)
python main.py live -c config.yaml -t 1h --confirm-live          # HYPE
python main.py live -c configs/config-eth.yaml -t 1h --confirm-live

# Перетюнинг
python scripts/tune_symbol.py -s ETH/USDC:USDC -o data/tune-eth.json
python scripts/build_symbol_config.py --tune data/tune-eth.json --out configs/config-eth.yaml
```

## Docker

Смонтируйте нужный конфиг:

```yaml
volumes:
  - ./configs/config-eth.yaml:/app/config.yaml:ro
command: ["live", "-t", "1h", "--confirm-live", "-c", "config.yaml"]
```

## Параметры по монетам

### BTC
- Медленнее: **EMA 20/50**, ST 10×3.0
- 15m: ST 10×3.5 | 1h: ST 10×2.5, vol 30 | 4h: ST 7×2.5
- `max_notional_usd: 2000`, bracket TP порог 0.08%

### ETH
- **EMA 9/21**, ST 10×**4.0** (широкий — меньше шума)
- 15m: ST 10×2.5 (уже) | 1d: vol 30
- `max_notional_usd: 1500`

### SUI
- База: ST **7×2.5** (быстрее реакция)
- 1h: ST 10×**3.5** | 15m/1d: ST 10×4.0
- Как HYPE по `max_notional_usd: 500`

### ZEC
- **EMA 12/26**, ST **7×2.5**, vol 20
- 15m: ST 10×4.0 | 1d: vol 30
- Live-like 1h: **+27.3%** (11 сделок, DD 4.5%)
- `bracket_tp_min_change_pct: 0.18`, `max_notional_usd: 500`

### HYPE (без изменений)
- EMA 9/21, 15m ST 10×4.0, 1h ST 10×2.5
- `bracket_tp_min_change_pct: 0.15` под цену ~$60

Результаты тюнинга: `data/tune-{btc,eth,sui,zec}.json`

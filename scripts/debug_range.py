from src.config import load_config
from src.data import fetch_ohlcv
from src.strategy.range_reversion import prepare_range_dataframe

config = load_config()
cfg = config.range_strategy
df = fetch_ohlcv(config.symbol, "4h", 1000, config.exchange.id)
data = prepare_range_dataframe(df, cfg)
adx, rsi = data["adx"], data["rsi"]
prev_adx, prev_rsi = adx.shift(1), rsi.shift(1)
prev_low, prev_high = data["low"].shift(1), data["high"].shift(1)
prev_close = data["close"].shift(1)
prev_bb_lower, prev_bb_upper = data["bb_lower"].shift(1), data["bb_upper"].shift(1)

narrow = data["bb_width_pct"] <= cfg.max_bb_width_pct
flat = adx < cfg.adx.max_for_entry
if cfg.require_adx_flat:
    flat &= adx <= prev_adx.fillna(adx)

touched_lower = prev_low <= prev_bb_lower
touched_upper = prev_high >= prev_bb_upper
was_oversold = prev_rsi < cfg.rsi.oversold
was_overbought = prev_rsi > cfg.rsi.overbought
bounce_up = (data["close"] > prev_close) & (rsi > prev_rsi.fillna(rsi)) & (data["close"] >= data["open"])
bounce_down = (data["close"] < prev_close) & (rsi < prev_rsi.fillna(rsi)) & (data["close"] <= data["open"])
reward_l = ((data["bb_middle"] - data["close"]) / data["close"] * 100) >= cfg.min_reward_to_middle_pct
reward_s = ((data["close"] - data["bb_middle"]) / data["close"] * 100) >= cfg.min_reward_to_middle_pct
down = (data["ema_fast"] < data["ema_slow"]) & (adx > cfg.counter_trend_adx)
up = (data["ema_fast"] > data["ema_slow"]) & (adx > cfg.counter_trend_adx)

long_s = narrow & flat & touched_lower & was_oversold & bounce_up & reward_l & ~down
short_s = narrow & flat & touched_upper & was_overbought & bounce_down & reward_s & ~up

for name, m in [
    ("touched_lower", touched_lower),
    ("was_oversold", was_oversold),
    ("bounce_up", bounce_up),
    ("all3", touched_lower & was_oversold & bounce_up),
    ("+narrow", touched_lower & was_oversold & bounce_up & narrow),
    ("+flat", touched_lower & was_oversold & bounce_up & narrow & flat),
    ("+reward", touched_lower & was_oversold & bounce_up & narrow & flat & reward_l),
    ("long_final", long_s),
    ("short_final", short_s),
]:
    print(name, int(m.sum()))

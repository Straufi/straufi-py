from datetime import timedelta

import pytest

from straufi import Config, Every, Frequency, Instrument, ValidationError
from straufi.indicators import ATR, EMA, MACD, RSI, SMA, BollingerBands

PEPE = Instrument("pepe", "usdt", "Binance")
DOGE = Instrument("DOGE", "USDT", "binance")


def test_instrument_normalization():
    assert Instrument("PEPE", "USDT", "binance") == PEPE
    assert str(PEPE) == "PEPE/USDT on binance"
    base, quote, broker = PEPE
    assert (base, quote, broker) == ("PEPE", "USDT", "binance")


def test_sample_config():
    config = Config(
        indicators={
            "atr14": ATR(period=14),
            "bb": BollingerBands(period=20),
            "emma": EMA(period=12, price_type="close"),
            "macd_12_26_9": MACD(short_period=12, long_period=26, signal_period=9),
            "rsi14": RSI(period=14),
            "ma_super_sma": SMA(period=20, price_type="close"),
        },
        lookback=24 * 120,
        interval="15min",
        frequency=Every("1h"),
        instruments={"pepe": PEPE, "doge": DOGE},
    )
    assert config.indicator_columns()["bb"] == {"upper": "bb_upper", "middle": "bb_middle", "lower": "bb_lower"}
    assert config.indicator_columns()["rsi14"] == {"rsi": "rsi14"}
    manifest = config.to_dict()
    assert manifest["version"] == 1
    assert manifest["indicators"]["macd_12_26_9"] == {
        "indicatorName": "macd",
        "parameters": {"shortPeriod": 12, "longPeriod": 26, "signalPeriod": 9, "priceType": "close"},
        "columns": {
            "macd": "macd_12_26_9_macd",
            "signal": "macd_12_26_9_signal",
        },
    }
    assert manifest["indicators"]["bb"] == {
        "indicatorName": "bollinger-bands",
        "parameters": {"period": 20, "priceType": "close"},
        "columns": {"upper": "bb_upper", "middle": "bb_middle", "lower": "bb_lower"},
    }
    assert manifest["indicators"]["atr14"] == {
        "indicatorName": "atr",
        "parameters": {"period": 14},
        "columns": {"atr": "atr14"},
    }
    assert manifest["interval"] == {"minutes": 15}
    assert manifest["frequency"] == {"type": "every", "minutes": 60}
    assert manifest["instruments"]["pepe"] == {"base": "PEPE", "quote": "USDT", "broker": "binance"}


def test_resolve_instruments():
    config = Config(instruments={"pepe": PEPE, "doge": DOGE}, lookback=10, interval="1h", frequency="1h")
    assert config.resolve_instrument("doge") == DOGE
    assert config.resolve_instrument(DOGE) == DOGE
    assert config.resolve_instrument_alias(DOGE) == "doge"
    assert config.resolve_instrument_alias("pepe") == "pepe"
    with pytest.raises(ValidationError, match=r"Unknown instrument 'eth'\. Your instruments are: 'pepe', 'doge'"):
        config.resolve_instrument("eth")
    with pytest.raises(ValidationError, match="not in your instruments"):
        config.resolve_instrument_alias(Instrument("BTC", "USDT", "binance"))


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"instruments": {}, "lookback": 10, "interval": "1h", "frequency": "1h"}, "can't be empty"),
        ({"instruments": [PEPE], "lookback": 10, "interval": "1h", "frequency": "1h"}, "must be a dict"),
        ({"instruments": {"a": PEPE, "b": PEPE}, "lookback": 10, "interval": "1h", "frequency": "1h"}, "appears twice"),
        ({"instruments": {"a": "PEPE"}, "lookback": 10, "interval": "1h", "frequency": "1h"}, "must be an Instrument"),
        ({"instruments": {"pepe": PEPE}, "lookback": 0, "interval": "1h", "frequency": "1h"}, "greater than 0"),
        ({"instruments": {"pepe": PEPE}, "lookback": 1.5, "interval": "1h", "frequency": "1h"}, "whole number"),
        (
            {"instruments": {"pepe": PEPE}, "lookback": 1, "interval": "1h", "frequency": Every},
            "forget the parentheses",
        ),
        ({"instruments": {"pepe": PEPE}, "lookback": 1, "interval": "1h", "frequency": 15}, "must be like"),
        (
            {"instruments": {"pepe": PEPE}, "lookback": 1, "interval": "7min", "frequency": "1h"},
            "interval must be one of",
        ),
        ({"instruments": {"pepe": PEPE}, "lookback": 1, "interval": 15, "frequency": "1h"}, "or a timedelta"),
        (
            {"instruments": {"pepe": PEPE}, "lookback": 1, "interval": "1h", "frequency": "30min"},
            "multiple of interval",
        ),
        (
            {"instruments": {"pepe": PEPE}, "lookback": 1, "interval": "20min", "frequency": "30min"},
            "multiple of interval",
        ),
        (
            {
                "instruments": {"pepe": PEPE},
                "lookback": 1,
                "interval": "1h",
                "frequency": "1h",
                "indicators": {"r": RSI},
            },
            "forget the parentheses",
        ),
        (
            {
                "instruments": {"pepe": PEPE},
                "lookback": 1,
                "interval": "1h",
                "frequency": "1h",
                "indicators": {"instrument": RSI()},
            },
            "reserved",
        ),
        (
            {
                "instruments": {"pepe": PEPE},
                "lookback": 1,
                "interval": "1h",
                "frequency": "1h",
                "indicators": {"bb": BollingerBands(), "bb_upper": SMA(5)},
            },
            "rename",
        ),
    ],
)
def test_invalid_configs(kwargs, message):
    with pytest.raises(ValidationError, match=message):
        Config(**kwargs)


def test_invalid_indicators():
    with pytest.raises(ValidationError, match="greater than 0"):
        RSI(period=0)
    with pytest.raises(ValidationError, match="must be smaller"):
        MACD(short_period=26, long_period=12)
    with pytest.raises(ValidationError, match="price_type"):
        SMA(period=5, price_type="median")


@pytest.mark.parametrize(
    ("frequency", "minutes"),
    [
        (Every("5min"), 5),
        (Every("15m"), 15),
        (Every(" 1H "), 60),
        (Every("2 hours"), 120),
        (Every(timedelta(hours=4)), 240),
        (Every(minutes=30), 30),
        (Every(hours=24), 24 * 60),
    ],
)
def test_every(frequency, minutes):
    assert frequency.minutes == minutes
    assert frequency == Every(timedelta(minutes=minutes))
    assert eval(repr(frequency)) == frequency


def test_interval():
    config = Config(instruments={"pepe": PEPE}, lookback=1, interval=timedelta(minutes=15), frequency="1h")
    assert config.interval == timedelta(minutes=15)
    assert Config(instruments={"pepe": PEPE}, lookback=1, interval="4h", frequency="12h").interval == timedelta(hours=4)


def test_frequency_shorthand():
    config = Config(instruments={"pepe": PEPE}, lookback=1, interval="15min", frequency="15min")
    assert config.frequency == Every("15min")
    assert isinstance(config.frequency, Frequency)
    match config.frequency:
        case Every(minutes=minutes):
            assert minutes == 15


@pytest.mark.parametrize(
    ("args", "kwargs", "message"),
    [
        (("3min",), {}, "must be one of"),
        (("7min",), {}, "must be one of"),
        (("60min",), {}, "must be one of"),
        (("5h",), {}, "must be one of"),
        ((), {"minutes": 0}, "must be one of"),
        ((), {"minutes": 90}, "must be one of"),
        ((), {"hours": 1, "minutes": 30}, "not both"),
        ((timedelta(minutes=90),), {}, "must be one of"),
        ((timedelta(seconds=30),), {}, "must be one of"),
        (("1h30min",), {}, "must be like"),
        (("1d",), {}, "must be like"),
        (("30s",), {}, "must be like"),
        (("",), {}, "must be like"),
        (("15",), {}, "must be like"),
        ((15,), {}, "or a timedelta"),
        (("1h",), {"minutes": 30}, "not both"),
        ((), {"minutes": 7.5}, "whole number"),
        ((), {"hours": -1, "minutes": 90}, "whole number"),
    ],
)
def test_invalid_every(args, kwargs, message):
    with pytest.raises(ValidationError, match=message):
        Every(*args, **kwargs)

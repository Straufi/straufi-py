import math
from datetime import UTC, datetime

import numpy as np
import pytest

from straufi import Instrument, Order, OrderSide, OrderStatus, OrderTimeInForce, OrderType, ValidationError

PEPE = Instrument("PEPE", "USDT", "binance")


def test_sample_stop_loss_limit_order():
    order = Order(
        instrument=PEPE,
        type=OrderType.STOP_LOSS_LIMIT,
        side=OrderSide.BUY,
        volume=100,
        time_in_force=OrderTimeInForce.GTC,
        limit_price=100.0,
        trigger_price=99.0,
        trailing_delta=0.5,
    )
    assert order.volume == 100.0 and isinstance(order.volume, float)
    assert order.is_new


def test_enums_accept_text_in_any_case():
    order = Order(instrument=PEPE, type="limit", side="Buy", volume=1, limit_price=2, time_in_force="ioc")
    assert (order.type, order.side, order.time_in_force) == (OrderType.LIMIT, OrderSide.BUY, OrderTimeInForce.IOC)
    assert Order(instrument=PEPE, type="stop-loss", side="sell", volume=1, trigger_price=1).type is OrderType.STOP_LOSS


def test_limit_orders_default_to_gtc():
    assert (
        Order(instrument=PEPE, type="LIMIT", side="BUY", volume=1, limit_price=2).time_in_force is OrderTimeInForce.GTC
    )
    assert Order(instrument=PEPE, type="LIMIT_MAKER", side="BUY", volume=1, limit_price=2).time_in_force is None


def test_numpy_numbers_are_accepted():
    order = Order(instrument=PEPE, type="LIMIT", side="BUY", volume=np.int64(3), limit_price=np.float64(1.5))
    assert (order.volume, order.limit_price) == (3.0, 1.5)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"type": "MARKET", "side": "BUY"}, "either volume"),
        ({"type": "MARKET", "side": "BUY", "volume": 1, "quote_volume": 1}, "either volume"),
        ({"type": "MARKET", "side": "BUY", "volume": 1, "limit_price": 1}, "limit_price can't be set"),
        ({"type": "MARKET", "side": "BUY", "volume": 1, "time_in_force": "GTC"}, "time_in_force can't be set"),
        ({"type": "LIMIT", "side": "BUY", "volume": 1}, "limit_price is required"),
        ({"type": "LIMIT", "side": "BUY", "quote_volume": 1, "limit_price": 1}, "volume is required"),
        ({"type": "LIMIT", "side": "BUY", "volume": -1, "limit_price": 1}, "greater than 0"),
        ({"type": "STOP_LOSS", "side": "SELL", "volume": 1}, "trigger_price, a trailing_delta"),
        ({"type": "ICEBERG", "side": "BUY", "volume": 10, "limit_price": 1}, "display_volume is required"),
        ({"type": "ICEBERG", "side": "BUY", "volume": 10, "limit_price": 1, "display_volume": 20}, "between 0"),
        ({"type": "LIMIT", "side": "BUY", "volume": 1, "limit_price": 1, "display_volume": 1}, "only ICEBERG"),
        ({"type": "FOO", "side": "BUY"}, "OrderType.MARKET"),
        ({"type": "MARKET", "side": "BUY", "volume": math.nan}, "NaN"),
        ({"type": "MARKET", "side": "BUY", "volume": "12"}, "must be a number"),
        ({"type": "MARKET", "side": "BUY", "volume": 1, "status": "NEW", "new_at": 1788256800}, "ISO 8601"),
    ],
)
def test_invalid_orders(kwargs, message):
    with pytest.raises(ValidationError, match=message):
        Order(instrument=PEPE, **kwargs)


def test_positions_round_trip_and_skip_new_order_rules():
    data = {
        "id": "1", "order_id": "b-1", "broker": "Binance", "base": "pepe", "quote": "usdt",
        "type": "LIMIT", "side": "BUY", "status": "PARTIALLY_FILLED", "in_order_book": True,
        "volume_traded": 5, "quote_volume_traded": 0.5, "volume": 10, "quote_volume": 1, "display_volume": 0,
        "time_in_force": "GTC", "limit_price": 0.1, "trigger_price": 0, "trailing_delta": 0,
        "submitted_at": "2026-09-01T10:00:00Z", "new_at": "2026-09-01T12:00:00+02:00", "triggered_at": None,
        "last_partially_filled_at": "2026-09-01T10:05:00", "some_future_field": "ignored",
    }  # fmt: skip
    order = Order.from_dict(data)
    assert order.status is OrderStatus.PARTIALLY_FILLED and not order.is_new
    assert order.instrument == PEPE
    assert order.submitted_at == datetime(2026, 9, 1, 10, tzinfo=UTC)
    assert order.new_at == datetime(2026, 9, 1, 10, tzinfo=UTC)
    assert Order.from_dict(order.to_dict()) == order


def test_repr_only_shows_set_fields():
    order = Order(instrument=PEPE, type="MARKET", side="BUY", volume=1)
    assert repr(order) == "Order(instrument=PEPE/USDT on binance, type=MARKET, side=BUY, volume=1.0)"


def test_instrument_is_flattened_in_dicts():
    order = Order(instrument=PEPE, type="MARKET", side="BUY", volume=1)
    assert order.to_dict() == {"base": "PEPE", "quote": "USDT", "broker": "binance", "type": "MARKET", "side": "BUY",
                               "volume": 1.0}  # fmt: skip
    assert Order.from_dict(order.to_dict()) == order
    nested = {"instrument": {"base": "pepe", "quote": "usdt", "broker": "Binance"}, "type": "MARKET", "side": "BUY",
              "volume": 1}  # fmt: skip
    assert Order.from_dict(nested) == order


def test_instrument_must_be_an_instrument():
    with pytest.raises(ValidationError, match="must be an Instrument"):
        Order(instrument="pepe", type="MARKET", side="BUY", volume=1)  # pyright: ignore[reportArgumentType]

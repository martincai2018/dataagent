import pytest
from sqlalchemy import create_engine, text


@pytest.fixture
def demo_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'demo.db'}")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE dws_trade_order_di ("
            "id INTEGER PRIMARY KEY, channel TEXT, city TEXT, order_pay_amt REAL, "
            "order_status TEXT, pay_time TEXT, dt TEXT)"
        ))
        rows = [
            (1, "web", "北京", 100.0, "paid", "2026-10-22 09:00:00", "2026-10-22"),
            (2, "app", "上海", 200.0, "paid", "2026-10-22 10:00:00", "2026-10-22"),
            (3, "app", "北京", 300.0, "paid", "2026-10-22 11:00:00", "2026-10-22"),
            (4, "web", "广州", 50.0, "refund", "2026-10-22 12:00:00", "2026-10-22"),
            (5, "app", "上海", 150.0, "paid", "2026-10-21 09:00:00", "2026-10-21"),
        ]
        for row in rows:
            conn.execute(text(
                "INSERT INTO dws_trade_order_di "
                "(id, channel, city, order_pay_amt, order_status, pay_time, dt) "
                f"VALUES {row}"
            ))
    yield engine
    engine.dispose()  # Windows tmp_path 回收要求（同 executor/metadata fixture）

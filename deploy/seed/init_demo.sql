CREATE TABLE IF NOT EXISTS dws_trade_order_di (
  id BIGINT PRIMARY KEY,
  channel VARCHAR(32) NOT NULL COMMENT '下单渠道',
  city VARCHAR(32) NOT NULL COMMENT '城市',
  order_pay_amt DECIMAL(12, 2) NOT NULL COMMENT '支付金额',
  order_status VARCHAR(16) NOT NULL COMMENT '订单状态: paid/refund',
  pay_time DATETIME NOT NULL COMMENT '支付时间',
  dt VARCHAR(10) NOT NULL COMMENT '分区日期 yyyy-MM-dd'
) COMMENT='交易订单日汇总（demo）';

INSERT INTO dws_trade_order_di (id, channel, city, order_pay_amt, order_status, pay_time, dt) VALUES
  (1, 'web', '北京', 100.00, 'paid',   '2026-10-22 09:00:00', '2026-10-22'),
  (2, 'app', '上海', 200.00, 'paid',   '2026-10-22 10:00:00', '2026-10-22'),
  (3, 'app', '北京', 300.00, 'paid',   '2026-10-22 11:00:00', '2026-10-22'),
  (4, 'web', '广州',  50.00, 'refund', '2026-10-22 12:00:00', '2026-10-22'),
  (5, 'app', '上海', 150.00, 'paid',   '2026-10-21 09:00:00', '2026-10-21'),
  (6, 'web', '北京',  80.00, 'paid',   '2026-10-21 14:00:00', '2026-10-21'),
  (7, 'app', '广州', 120.00, 'paid',   '2026-10-21 15:00:00', '2026-10-21'),
  (8, 'web', '上海',  40.00, 'refund', '2026-10-21 16:00:00', '2026-10-21');

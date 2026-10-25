-- 官方镜像先建 reader 并授 demo.* ALL；这里收权为纯只读，由 /docker-entrypoint-initdb.d
-- 按文件名字典序执行（00_ 在 init_demo.sql 之前；GRANT ON db.* 不要求表已存在）
REVOKE ALL PRIVILEGES, GRANT OPTION FROM 'reader'@'%';
GRANT SELECT ON demo.* TO 'reader'@'%';
FLUSH PRIVILEGES;

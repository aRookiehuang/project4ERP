-- 开发演示密码。用于专用、全新 MySQL 实例；部署时修改密码并同步 .env。
CREATE DATABASE IF NOT EXISTS erp_demo CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS nlq_app CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'query_reader'@'%' IDENTIFIED BY 'local-reader-change-me';
CREATE USER IF NOT EXISTS 'app_writer'@'%' IDENTIFIED BY 'local-writer-change-me';
CREATE USER IF NOT EXISTS 'demo_seed'@'%' IDENTIFIED BY 'local-seed-change-me';
GRANT SELECT, INSERT, CREATE, ALTER, INDEX, REFERENCES ON erp_demo.* TO 'demo_seed'@'%';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, REFERENCES ON nlq_app.* TO 'app_writer'@'%';
-- 六表由 python -m backend.seed 创建，然后执行 grant-reader.sql。

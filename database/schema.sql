-- MySQL 8.4 business schema; generated from backend/app/models.py.
USE erp_demo;
CREATE TABLE categories (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	name VARCHAR(100) NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE customers (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	customer_code VARCHAR(30) NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	region VARCHAR(30) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (customer_code)
);

CREATE TABLE salespeople (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	name VARCHAR(100) NOT NULL, 
	department VARCHAR(100) NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE orders (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	order_no VARCHAR(30) NOT NULL, 
	customer_id INTEGER NOT NULL, 
	salesperson_id INTEGER NOT NULL, 
	sales_region VARCHAR(30) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	created_at DATETIME NOT NULL, 
	paid_at DATETIME, 
	paid_amount NUMERIC(18, 2) NOT NULL, 
	PRIMARY KEY (id), 
	CHECK (status IN ('PENDING','CANCELLED','PAID','SHIPPED','COMPLETED')), 
	CHECK (status NOT IN ('PAID','SHIPPED','COMPLETED') OR paid_at IS NOT NULL), 
	CHECK (paid_amount >= 0), 
	UNIQUE (order_no), 
	FOREIGN KEY(customer_id) REFERENCES customers (id), 
	FOREIGN KEY(salesperson_id) REFERENCES salespeople (id)
);

CREATE INDEX ix_orders_customer_paid ON orders (customer_id, paid_at);
CREATE INDEX ix_orders_paid_status ON orders (paid_at, status);
CREATE INDEX ix_orders_region_paid ON orders (sales_region, paid_at);
CREATE INDEX ix_orders_salesperson_id ON orders (salesperson_id);
CREATE TABLE products (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	sku VARCHAR(30) NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	category_id INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (sku), 
	FOREIGN KEY(category_id) REFERENCES categories (id)
);

CREATE INDEX ix_products_category_id ON products (category_id);
CREATE TABLE order_items (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	order_id INTEGER NOT NULL, 
	product_id INTEGER NOT NULL, 
	quantity INTEGER NOT NULL, 
	unit_price NUMERIC(18, 2) NOT NULL, 
	line_paid_amount NUMERIC(18, 2) NOT NULL, 
	PRIMARY KEY (id), 
	CHECK (quantity > 0), 
	CHECK (line_paid_amount >= 0), 
	FOREIGN KEY(order_id) REFERENCES orders (id), 
	FOREIGN KEY(product_id) REFERENCES products (id)
);

CREATE INDEX ix_items_product_order ON order_items (product_id, order_id);
CREATE INDEX ix_order_items_order_id ON order_items (order_id);

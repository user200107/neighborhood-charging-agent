-- 邻里充电 · PostgreSQL 参考建表脚本

-- 由 SQLAlchemy 模型生成；应用启动时也会自动 create_all。

-- 生产环境建议使用 Alembic 迁移。



CREATE TABLE tenants (
	id SERIAL NOT NULL, 
	code VARCHAR(40) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	contact_name VARCHAR(60), 
	contact_phone VARCHAR(30), 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (code)
);

CREATE TABLE communities (
	id SERIAL NOT NULL, 
	tenant_id INTEGER NOT NULL, 
	code VARCHAR(30) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	city VARCHAR(60) NOT NULL, 
	address VARCHAR(255), 
	status VARCHAR(20) NOT NULL, 
	contact_name VARCHAR(60), 
	contact_phone VARCHAR(30), 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_community_tenant_code UNIQUE (tenant_id, code), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

CREATE TABLE users (
	id SERIAL NOT NULL, 
	tenant_id INTEGER NOT NULL, 
	username VARCHAR(60) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	display_name VARCHAR(60) NOT NULL, 
	role VARCHAR(20) NOT NULL, 
	phone VARCHAR(30), 
	email VARCHAR(120), 
	status VARCHAR(20) NOT NULL, 
	last_login_at TIMESTAMP WITHOUT TIME ZONE, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_user_tenant_username UNIQUE (tenant_id, username), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

CREATE TABLE agent_memories (
	id SERIAL NOT NULL, 
	tenant_id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	kind VARCHAR(20) NOT NULL, 
	content TEXT NOT NULL, 
	tags JSON NOT NULL, 
	expires_at TIMESTAMP WITHOUT TIME ZONE, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE approvals (
	id SERIAL NOT NULL, 
	tenant_id INTEGER NOT NULL, 
	approval_no VARCHAR(40) NOT NULL, 
	type VARCHAR(30) NOT NULL, 
	risk_level VARCHAR(20) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	community_id INTEGER, 
	requester_id INTEGER NOT NULL, 
	approver_id INTEGER, 
	target_type VARCHAR(30) NOT NULL, 
	target_id VARCHAR(60) NOT NULL, 
	target_name VARCHAR(160), 
	amount FLOAT NOT NULL, 
	impact_scope VARCHAR(255) NOT NULL, 
	reason TEXT NOT NULL, 
	payload JSON NOT NULL, 
	decision_comment VARCHAR(255), 
	execution_result JSON, 
	decided_at TIMESTAMP WITHOUT TIME ZONE, 
	executed_at TIMESTAMP WITHOUT TIME ZONE, 
	source VARCHAR(20) NOT NULL, 
	trace_id VARCHAR(40), 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_approval_tenant_no UNIQUE (tenant_id, approval_no), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE, 
	FOREIGN KEY(community_id) REFERENCES communities (id) ON DELETE SET NULL, 
	FOREIGN KEY(requester_id) REFERENCES users (id) ON DELETE RESTRICT, 
	FOREIGN KEY(approver_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE TABLE audit_logs (
	id SERIAL NOT NULL, 
	tenant_id INTEGER NOT NULL, 
	trace_id VARCHAR(40), 
	actor_id INTEGER, 
	actor_name VARCHAR(60) NOT NULL, 
	actor_role VARCHAR(20) NOT NULL, 
	action VARCHAR(60) NOT NULL, 
	resource_type VARCHAR(40) NOT NULL, 
	resource_id VARCHAR(60) NOT NULL, 
	detail JSON NOT NULL, 
	ip VARCHAR(60), 
	result VARCHAR(20) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE, 
	FOREIGN KEY(actor_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE TABLE idempotency_records (
	id SERIAL NOT NULL, 
	tenant_id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	endpoint VARCHAR(120) NOT NULL, 
	key VARCHAR(120) NOT NULL, 
	request_hash VARCHAR(64) NOT NULL, 
	status_code INTEGER NOT NULL, 
	response JSON NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	expires_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_idempotency_scope UNIQUE (tenant_id, user_id, endpoint, key), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE refresh_tokens (
	id SERIAL NOT NULL, 
	tenant_id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	token_hash VARCHAR(64) NOT NULL, 
	expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	revoked_at TIMESTAMP WITHOUT TIME ZONE, 
	user_agent VARCHAR(255), 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE user_communities (
	user_id INTEGER NOT NULL, 
	community_id INTEGER NOT NULL, 
	PRIMARY KEY (user_id, community_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(community_id) REFERENCES communities (id) ON DELETE CASCADE
);

CREATE TABLE zones (
	id SERIAL NOT NULL, 
	tenant_id INTEGER NOT NULL, 
	community_id INTEGER NOT NULL, 
	code VARCHAR(30) NOT NULL, 
	name VARCHAR(80) NOT NULL, 
	description VARCHAR(255), 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_zone_community_code UNIQUE (community_id, code), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE, 
	FOREIGN KEY(community_id) REFERENCES communities (id) ON DELETE CASCADE
);

CREATE TABLE agent_runs (
	id SERIAL NOT NULL, 
	trace_id VARCHAR(40) NOT NULL, 
	tenant_id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	session_id VARCHAR(60) NOT NULL, 
	input TEXT NOT NULL, 
	intent VARCHAR(40) NOT NULL, 
	risk_level VARCHAR(20) NOT NULL, 
	status VARCHAR(24) NOT NULL, 
	answer TEXT NOT NULL, 
	tool_calls JSON NOT NULL, 
	sources JSON NOT NULL, 
	approval_id INTEGER, 
	latency_ms INTEGER NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(approval_id) REFERENCES approvals (id) ON DELETE SET NULL
);

CREATE TABLE piles (
	id SERIAL NOT NULL, 
	tenant_id INTEGER NOT NULL, 
	community_id INTEGER NOT NULL, 
	zone_id INTEGER, 
	code VARCHAR(40) NOT NULL, 
	name VARCHAR(80) NOT NULL, 
	model VARCHAR(60) NOT NULL, 
	vendor VARCHAR(60) NOT NULL, 
	rated_power_kw FLOAT NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	online BOOLEAN NOT NULL, 
	last_heartbeat_at TIMESTAMP WITHOUT TIME ZONE, 
	current_power_kw FLOAT NOT NULL, 
	temperature_c FLOAT NOT NULL, 
	signal_strength INTEGER NOT NULL, 
	firmware VARCHAR(30) NOT NULL, 
	installed_at TIMESTAMP WITHOUT TIME ZONE, 
	notes VARCHAR(255), 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_pile_tenant_code UNIQUE (tenant_id, code), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE, 
	FOREIGN KEY(community_id) REFERENCES communities (id) ON DELETE CASCADE, 
	FOREIGN KEY(zone_id) REFERENCES zones (id) ON DELETE SET NULL
);

CREATE TABLE connectors (
	id SERIAL NOT NULL, 
	tenant_id INTEGER NOT NULL, 
	pile_id INTEGER NOT NULL, 
	code VARCHAR(20) NOT NULL, 
	gun_type VARCHAR(20) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	power_kw FLOAT NOT NULL, 
	price_per_kwh FLOAT NOT NULL, 
	service_fee FLOAT NOT NULL, 
	total_energy_kwh FLOAT NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_connector_pile_code UNIQUE (pile_id, code), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE, 
	FOREIGN KEY(pile_id) REFERENCES piles (id) ON DELETE CASCADE
);

CREATE TABLE reservations (
	id SERIAL NOT NULL, 
	tenant_id INTEGER NOT NULL, 
	community_id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	connector_id INTEGER NOT NULL, 
	starts_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	ends_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	note VARCHAR(255), 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE, 
	FOREIGN KEY(community_id) REFERENCES communities (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(connector_id) REFERENCES connectors (id) ON DELETE CASCADE
);

CREATE TABLE orders (
	id SERIAL NOT NULL, 
	tenant_id INTEGER NOT NULL, 
	order_no VARCHAR(40) NOT NULL, 
	user_id INTEGER NOT NULL, 
	community_id INTEGER NOT NULL, 
	pile_id INTEGER NOT NULL, 
	connector_id INTEGER NOT NULL, 
	reservation_id INTEGER, 
	status VARCHAR(24) NOT NULL, 
	starts_at TIMESTAMP WITHOUT TIME ZONE, 
	ended_at TIMESTAMP WITHOUT TIME ZONE, 
	energy_kwh FLOAT NOT NULL, 
	unit_price FLOAT NOT NULL, 
	service_fee FLOAT NOT NULL, 
	amount FLOAT NOT NULL, 
	refund_amount FLOAT NOT NULL, 
	payment_method VARCHAR(20) NOT NULL, 
	idempotency_key VARCHAR(120), 
	cancel_reason VARCHAR(255), 
	source VARCHAR(20) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_order_tenant_no UNIQUE (tenant_id, order_no), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT, 
	FOREIGN KEY(community_id) REFERENCES communities (id) ON DELETE RESTRICT, 
	FOREIGN KEY(pile_id) REFERENCES piles (id) ON DELETE RESTRICT, 
	FOREIGN KEY(connector_id) REFERENCES connectors (id) ON DELETE RESTRICT, 
	FOREIGN KEY(reservation_id) REFERENCES reservations (id) ON DELETE SET NULL
);

CREATE TABLE tickets (
	id SERIAL NOT NULL, 
	tenant_id INTEGER NOT NULL, 
	ticket_no VARCHAR(40) NOT NULL, 
	community_id INTEGER NOT NULL, 
	pile_id INTEGER, 
	title VARCHAR(160) NOT NULL, 
	description TEXT, 
	priority VARCHAR(4) NOT NULL, 
	status VARCHAR(24) NOT NULL, 
	source VARCHAR(20) NOT NULL, 
	reporter_id INTEGER, 
	assignee_id INTEGER, 
	resolution TEXT, 
	heartbeat_checked BOOLEAN NOT NULL, 
	test_order_verified BOOLEAN NOT NULL, 
	test_order_id INTEGER, 
	sla_due_at TIMESTAMP WITHOUT TIME ZONE, 
	accepted_at TIMESTAMP WITHOUT TIME ZONE, 
	started_at TIMESTAMP WITHOUT TIME ZONE, 
	resolved_at TIMESTAMP WITHOUT TIME ZONE, 
	closed_at TIMESTAMP WITHOUT TIME ZONE, 
	escalation_count INTEGER NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_ticket_tenant_no UNIQUE (tenant_id, ticket_no), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE, 
	FOREIGN KEY(community_id) REFERENCES communities (id) ON DELETE CASCADE, 
	FOREIGN KEY(pile_id) REFERENCES piles (id) ON DELETE SET NULL, 
	FOREIGN KEY(reporter_id) REFERENCES users (id) ON DELETE SET NULL, 
	FOREIGN KEY(assignee_id) REFERENCES users (id) ON DELETE SET NULL, 
	FOREIGN KEY(test_order_id) REFERENCES orders (id) ON DELETE SET NULL
);

CREATE TABLE device_events (
	id SERIAL NOT NULL, 
	tenant_id INTEGER NOT NULL, 
	event_no VARCHAR(80) NOT NULL, 
	pile_id INTEGER NOT NULL, 
	connector_id INTEGER, 
	event_type VARCHAR(30) NOT NULL, 
	severity VARCHAR(20) NOT NULL, 
	payload JSON NOT NULL, 
	occurred_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	processed_at TIMESTAMP WITHOUT TIME ZONE, 
	ticket_id INTEGER, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_event_tenant_no UNIQUE (tenant_id, event_no), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE, 
	FOREIGN KEY(pile_id) REFERENCES piles (id) ON DELETE CASCADE, 
	FOREIGN KEY(connector_id) REFERENCES connectors (id) ON DELETE SET NULL, 
	FOREIGN KEY(ticket_id) REFERENCES tickets (id) ON DELETE SET NULL
);

CREATE INDEX ix_tenants_created_at ON tenants (created_at);

CREATE INDEX ix_communities_tenant_id ON communities (tenant_id);

CREATE INDEX ix_communities_created_at ON communities (created_at);

CREATE INDEX ix_users_created_at ON users (created_at);

CREATE INDEX ix_users_tenant_id ON users (tenant_id);

CREATE INDEX ix_users_role ON users (role);

CREATE INDEX ix_agent_memories_tenant_id ON agent_memories (tenant_id);

CREATE INDEX ix_agent_memories_created_at ON agent_memories (created_at);

CREATE INDEX ix_agent_memories_user_id ON agent_memories (user_id);

CREATE INDEX ix_approvals_tenant_id ON approvals (tenant_id);

CREATE INDEX ix_approval_scope ON approvals (tenant_id, status, risk_level);

CREATE INDEX ix_approvals_type ON approvals (type);

CREATE INDEX ix_approvals_created_at ON approvals (created_at);

CREATE INDEX ix_approvals_trace_id ON approvals (trace_id);

CREATE INDEX ix_approvals_status ON approvals (status);

CREATE INDEX ix_audit_logs_tenant_id ON audit_logs (tenant_id);

CREATE INDEX ix_audit_scope ON audit_logs (tenant_id, created_at);

CREATE INDEX ix_audit_logs_created_at ON audit_logs (created_at);

CREATE INDEX ix_audit_logs_action ON audit_logs (action);

CREATE INDEX ix_audit_logs_trace_id ON audit_logs (trace_id);

CREATE INDEX ix_idempotency_records_tenant_id ON idempotency_records (tenant_id);

CREATE INDEX ix_refresh_tokens_tenant_id ON refresh_tokens (tenant_id);

CREATE UNIQUE INDEX ix_refresh_tokens_token_hash ON refresh_tokens (token_hash);

CREATE INDEX ix_refresh_tokens_user_id ON refresh_tokens (user_id);

CREATE INDEX ix_zones_community_id ON zones (community_id);

CREATE INDEX ix_zones_created_at ON zones (created_at);

CREATE INDEX ix_zones_tenant_id ON zones (tenant_id);

CREATE INDEX ix_agent_runs_tenant_id ON agent_runs (tenant_id);

CREATE UNIQUE INDEX ix_agent_runs_trace_id ON agent_runs (trace_id);

CREATE INDEX ix_agent_runs_created_at ON agent_runs (created_at);

CREATE INDEX ix_agent_runs_session_id ON agent_runs (session_id);

CREATE INDEX ix_agent_runs_user_id ON agent_runs (user_id);

CREATE INDEX ix_piles_tenant_id ON piles (tenant_id);

CREATE INDEX ix_pile_scope ON piles (tenant_id, community_id, status);

CREATE INDEX ix_piles_created_at ON piles (created_at);

CREATE INDEX ix_piles_community_id ON piles (community_id);

CREATE INDEX ix_connectors_pile_id ON connectors (pile_id);

CREATE INDEX ix_connectors_tenant_id ON connectors (tenant_id);

CREATE INDEX ix_connectors_created_at ON connectors (created_at);

CREATE INDEX ix_reservations_user_id ON reservations (user_id);

CREATE INDEX ix_reservations_tenant_id ON reservations (tenant_id);

CREATE INDEX ix_reservations_connector_id ON reservations (connector_id);

CREATE INDEX ix_reservation_conflict ON reservations (connector_id, status, starts_at, ends_at);

CREATE INDEX ix_reservations_community_id ON reservations (community_id);

CREATE INDEX ix_reservations_created_at ON reservations (created_at);

CREATE INDEX ix_orders_status ON orders (status);

CREATE INDEX ix_orders_tenant_id ON orders (tenant_id);

CREATE INDEX ix_orders_pile_id ON orders (pile_id);

CREATE INDEX ix_orders_community_id ON orders (community_id);

CREATE INDEX ix_orders_created_at ON orders (created_at);

CREATE INDEX ix_orders_user_id ON orders (user_id);

CREATE INDEX ix_orders_idempotency_key ON orders (idempotency_key);

CREATE INDEX ix_orders_connector_id ON orders (connector_id);

CREATE INDEX ix_order_scope ON orders (tenant_id, community_id, status, created_at);

CREATE INDEX ix_tickets_tenant_id ON tickets (tenant_id);

CREATE INDEX ix_tickets_community_id ON tickets (community_id);

CREATE INDEX ix_tickets_assignee_id ON tickets (assignee_id);

CREATE INDEX ix_tickets_status ON tickets (status);

CREATE INDEX ix_ticket_scope ON tickets (tenant_id, community_id, status, priority);

CREATE INDEX ix_tickets_created_at ON tickets (created_at);

CREATE INDEX ix_tickets_pile_id ON tickets (pile_id);

CREATE INDEX ix_tickets_priority ON tickets (priority);

CREATE INDEX ix_device_events_created_at ON device_events (created_at);

CREATE INDEX ix_device_events_event_type ON device_events (event_type);

CREATE INDEX ix_device_events_pile_id ON device_events (pile_id);

CREATE INDEX ix_device_events_tenant_id ON device_events (tenant_id);

CREATE INDEX ix_event_pile_time ON device_events (pile_id, occurred_at);

drop table dvm cascade;
drop table dvm_state;
drop table dvm_transactions;


CREATE TABLE IF NOT EXISTS dvm (
	contract_hash CHAR(64) UNIQUE,
	creation_transaction CHAR(64) NOT NULL REFERENCES transactions(tx_hash) ON DELETE CASCADE,
	source_code BYTEA NOT NULL
);

CREATE TABLE IF NOT EXISTS dvm_state (
	contract_hash CHAR(64) NOT NULL REFERENCES dvm(contract_hash) ON DELETE CASCADE,
	block_no INT REFERENCES blocks(id) ON DELETE CASCADE,
	state JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS dvm_transactions (
    contract_hash CHAR(64) NOT NULL REFERENCES dvm(contract_hash) ON DELETE CASCADE,
	tx_hash CHAR(64) NOT NULL REFERENCES transactions(tx_hash) ON DELETE CASCADE,
	output_index SMALLINT NOT NULL,
	payload TEXT NOT NULL,
	UNIQUE (tx_hash, output_index)
);

CREATE TABLE IF NOT EXISTS dvm_events (
	tx_hash CHAR(64) NOT NULL,
	output_index SMALLINT NOT NULL,
	contract_hash CHAR(64) NOT NULL REFERENCES dvm(contract_hash) ON DELETE CASCADE,
	name TEXT NOT NULL,
	args JSONB NOT NULL,
	FOREIGN KEY (tx_hash, output_index) REFERENCES dvm_transactions (tx_hash, output_index)
);
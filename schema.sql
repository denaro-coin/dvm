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
	payload TEXT NOT NULL,
	method TEXT NOT NULL
);
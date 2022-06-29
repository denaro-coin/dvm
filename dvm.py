import json
import zlib
from decimal import Decimal

from RestrictedPython import compile_restricted, safe_builtins
from denaro import Database

from contract import ContractCreation, Contract, _write_, LimitedContract, Address
from serializer import deserialize


class DVM:
    def __init__(self, database: Database):
        self.database = database

    async def create_contract(self, contract_creation: ContractCreation, contract_hash: str, tx_hash: str, block_no: int, sender: str, args):
        byte_code = compile_restricted(contract_creation.source_code, f'Contract <{contract_hash}>', 'exec')
        contract = Contract(contract_hash, {}, {})
        contract_globals = safe_builtins | {'self': contract, 'Decimal': Decimal, '_write_': _write_, 'Contract': LimitedContract}
        try:
            exec(byte_code, contract_globals, {})
        except Exception as e:
            print(f'Contract has not been deployed because of a {e.__class__.__name__}: {str(e)} exception occurred while executing bytecode')
            return
        if 'constructor' in contract._methods:
            try:
                contract.constructor(Address(sender), *args)
            except Exception as e:
                print(f'Contract has not been deployed because of a {e.__class__.__name__}: {str(e)} exception occurred while executing constructor')
                return
        async with self.database.pool.acquire() as connection:
            await connection.execute(
                'INSERT INTO dvm(contract_hash, creation_transaction, bytecode) VALUES ($1, $2, $3)',
                contract_hash,
                tx_hash,
                # fixme: temp using source code instead of byte code; if bytecode cannot be used, rename bytecode in something else
                zlib.compress(contract_creation.source_code.encode())
            )
            print(f'Created contract {contract_hash}')
            try:
                contract_state = contract.get_json_state()
            except Exception as e:
                print(f'Contract state set to empty because there has been an {e.__class__.__name__}: {str(e)} exception while encoding data in constructor')
                return
            await connection.execute(
                'INSERT INTO dvm_state(contract_hash, block_no, state) VALUES ($1, $2, $3)',
                contract_hash,
                block_no,
                contract_state
            )

    async def get_contracts(self, contracts_hashes: list, all=False):
        # fixme remove "all" parameter
        async with self.database.pool.acquire() as connection:
            res = await connection.fetch(
                'SELECT contract_hash, bytecode FROM dvm WHERE true' if all else
                'SELECT contract_hash, bytecode FROM dvm WHERE contract_hash = ANY($1)',
                #contracts_hashes,
            )
        contracts_states = await self.get_contract_states(contracts_hashes, all)
        contracts = {}
        for res in res:
            contract_hash, bytecode = res
            bytecode = zlib.decompress(bytecode).decode()
            byte_code = compile_restricted(bytecode, f'Contract <{contract_hash}>', 'exec')
            contract = Contract(contract_hash, contracts_states[contract_hash], {})
            contract_globals = safe_builtins | {'self': contract, 'Decimal': Decimal, '_write_': _write_,'Contract': LimitedContract}
            try:
                exec(byte_code, contract_globals, {})
            except Exception as e:
                #print(bytecode)
                print(f'Contract {contract_hash} has not been get because a {e.__class__.__name__}: {str(e)} exception occurred while executing bytecode')
                #raise
                continue
            contracts[contract_hash] = contract
        return contracts

    async def get_contract_states(self, contract_hashes: list, all=False):
        async with self.database.pool.acquire() as connection:
            res = await connection.fetch(
                'SELECT DISTINCT ON (contract_hash) contract_hash, state FROM dvm_state WHERE true ORDER BY contract_hash, block_no DESC' if all else
                'SELECT DISTINCT ON (contract_hash) contract_hash, state FROM dvm_state WHERE contract_hash = ANY($1) ORDER BY contract_hash, block_no DESC',
                #contract_hashes,
            )
        return {contract_hash: {} for contract_hash in contract_hashes} | {contract_hash: {k: deserialize(bytes.fromhex(v)) for k, v in json.loads(state).items()} for contract_hash, state in res}

    async def update_contract_states(self, contract_states: dict, block_no: int):
        async with self.database.pool.acquire() as connection:
            # todo: add insert into dvm_transactions
            await connection.executemany(
                'INSERT INTO dvm_state(contract_hash, state, block_no) VALUES($1, $2, $3)',
                [(contract_hash, state, block_no) for contract_hash, state in contract_states.items()],
            )


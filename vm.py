import json
import zlib
from copy import deepcopy
from decimal import Decimal

from RestrictedPython import compile_restricted, safe_builtins, RestrictingNodeTransformer
from RestrictedPython.Eval import default_guarded_getiter, default_guarded_getitem
from RestrictedPython.Guards import guarded_iter_unpack_sequence, guarded_unpack_sequence, full_write_guard
from denaro import Database

from dvm.contract import ContractCreation, Contract, LimitedContract, Address, Event, ContractsCache, \
    CONTRACT_METHOD_TIMEOUT
from dvm.serializer import deserialize
from dvm.timeout import timeout


def _write_(obj):
    if isinstance(obj, Contract) and obj.__class__ != LimitedContract:
        return obj
    if type(obj) in (dict, list):
        return obj
    raise Exception(f'Cannot write to {obj.__class__.__name__}')


def _inplacevar_(op: str, value, arg):
    if op == '+=':
        return value + arg
    elif op == '-=':
        return value - arg
    else:
        raise NotImplementedError(f'Operator {op} not implemented')


class NonOverridable(type):
    def __new__(mcs, name, bases, dct):
        if Contract in bases and any(d in dir(Contract) for d in dct if d not in ('__module__', '__qualname__')):
            raise SyntaxError("Overriding Contract methods is not allowed")
        return type.__new__(mcs, name, bases, dct)


async def load_contract(contract_hash: str):
    if contract_hash not in ContractsCache.contracts:
        contract = (await DVM.instance.get_contracts([contract_hash]))[contract_hash]
        ContractsCache.contracts[contract_hash] = contract
        ContractsCache.contracts_backup[contract_hash] = deepcopy(contract)
    return LimitedContract(contract_hash)


contract_globals = safe_builtins | {
    'Decimal': Decimal, '_write_': _write_, '_inplacevar_': _inplacevar_,
    'Contract': Contract, 'load_contract': load_contract,
    'Event': Event,
    '__metaclass__': NonOverridable, '__name__': 'dvm_contract',
    '_iter_unpack_sequence_': guarded_iter_unpack_sequence,
    '_unpack_sequence_': guarded_unpack_sequence,
    '_getiter_': default_guarded_getiter,
    '_getitem_': default_guarded_getitem
}


class DVMNodeTransformer(RestrictingNodeTransformer):
    def visit_AsyncFunctionDef(self, node):
        """Allow async functions."""
        return self.node_contents_visit(node)

    def visit_Await(self, node):
        """Allow async functionality."""
        return self.node_contents_visit(node)


class DVM:
    instance: "DVM" = None

    def __init__(self, database: Database):
        self.database = database
        DVM.instance = self

    async def create_contract(self, contract_creation: ContractCreation, contract_hash: str, tx_hash: str, block_no: int, sender: str, args, kwargs={}):
        try:
            bytecode = compile_restricted(contract_creation.source_code, f'Contract <{contract_hash}>', policy=DVMNodeTransformer)
            exec(bytecode, contract_globals, {})
            contract = Contract.deployed(contract_hash, {})
            Contract.deployed = None
        except Exception as e:
            print(f'Contract has not been deployed because of a {e.__class__.__name__}: {str(e)} exception occurred while executing bytecode')
            raise
            return False
        if 'constructor' in contract._methods:
            ContractsCache.current_contract_hash = contract_hash
            ContractsCache.contract_instances = [contract_hash]
            try:
                await timeout(CONTRACT_METHOD_TIMEOUT, contract._methods['constructor'], Address(sender), *args, **kwargs)
            except Exception as e:
                print(f'Contract has not been deployed because of a {e.__class__.__name__}: {str(e)} exception occurred while executing constructor')
                return False
        try:
            contract_state = contract.get_json_state()
        except Exception as e:
            print(f'Contract has not been deployed because there has been an {e.__class__.__name__}: {str(e)} exception while encoding data in constructor')
            return False
        async with self.database.pool.acquire() as connection:
            await connection.execute(
                'INSERT INTO dvm(contract_hash, creation_transaction, source_code) VALUES ($1, $2, $3)',
                contract_hash,
                tx_hash,
                zlib.compress(contract_creation.source_code.encode())
            )
            await connection.execute(
                'INSERT INTO dvm_state(contract_hash, block_no, state) VALUES ($1, $2, $3)',
                contract_hash,
                block_no,
                contract_state
            )
        print(f'Created contract {contract_hash}')
        ContractsCache.contracts[contract_hash] = contract
        return contract

    async def get_contracts(self, contracts_hashes: list):
        async with self.database.pool.acquire() as connection:
            res = await connection.fetch('SELECT contract_hash, source_code FROM dvm WHERE contract_hash = ANY($1)', contracts_hashes)
        contracts_states = await self.get_contract_states(contracts_hashes)
        contracts = {}
        for res in res:
            contract_hash, source_code = res
            source_code = zlib.decompress(source_code).decode()
            bytecode = compile_restricted(source_code, f'Contract <{contract_hash}>', policy=DVMNodeTransformer)
            try:
                exec(bytecode, contract_globals, {})
                contract = Contract.deployed(contract_hash, contracts_states[contract_hash])
                Contract.deployed = None
            except Exception as e:
                print(f'Contract {contract_hash} has not been get because a {e.__class__.__name__}: {str(e)} exception occurred while executing bytecode')
                continue
            contracts[contract_hash] = contract
        return contracts

    async def get_contract_states(self, contract_hashes: list):
        async with self.database.pool.acquire() as connection:
            res = await connection.fetch(
                'SELECT DISTINCT ON (contract_hash) contract_hash, state FROM dvm_state WHERE contract_hash = ANY($1) ORDER BY contract_hash, block_no DESC',
                contract_hashes
            )
        return {contract_hash: {k: deserialize(bytes.fromhex(v)) for k, v in json.loads(state).items()} for contract_hash, state in res}

    async def get_contracts_source(self, contracts_hashes: list):
        async with self.database.pool.acquire() as connection:
            rows = await connection.fetch('SELECT contract_hash, source_code FROM dvm WHERE contract_hash = ANY($1)', contracts_hashes)
        return {row['contract_hash']: row['source_code'] for row in rows}

    async def update_contract_states(self, contract_states: dict, block_no: int):
        async with self.database.pool.acquire() as connection:
            await connection.executemany(
                'INSERT INTO dvm_state(contract_hash, state, block_no) VALUES($1, $2, $3)',
                [(contract_hash, state, block_no) for contract_hash, state in contract_states.items()],
            )

    async def add_transactions(self, rows: list):
        async with self.database.pool.acquire() as connection:
            await connection.executemany(
                'INSERT INTO dvm_transactions(contract_hash, tx_hash, output_index, payload) VALUES($1, $2, $3, $4)',
                rows
            )
    
    async def add_events(self, rows: list):
        async with self.database.pool.acquire() as connection:
            await connection.executemany(
                'INSERT INTO dvm_events(tx_hash, output_index, contract_hash, name, args) VALUES($1, $2, $3, $4, $5)',
                rows
            )

    async def read_contract(self, contract_hash: str, method: str, args: tuple):
        contracts = await self.get_contracts([contract_hash])
        contract = contracts[contract_hash]
        if method in contract._variables:
            return contract._variables[method]
        return contract._methods[method](*args)

    # contract VM methods

    async def get_block(self, block_no_or_block_hash: str | int):
        ContractsCache.additional_gas += 512
        block = await (self.database.get_block(block_no_or_block_hash) if isinstance(block_no_or_block_hash, str) else self.database.get_block_by_id(block_no_or_block_hash))
        if not block:
            raise Exception(f'Block {block_no_or_block_hash} not found')
        return block

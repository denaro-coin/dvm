import asyncio
import json
import zlib
from asyncio import sleep
from decimal import Decimal
from threading import Thread
from os import environ

from RestrictedPython import compile_restricted, safe_builtins

from denaro import Database
from denaro.helpers import sha256, point_to_string
from denaro.transactions import CoinbaseTransaction
from contract import ContractCall, ContractCreation, Contract, _write_, LimitedContract, deserialize, ContractsCache, \
    Address
from dvm import DVM

Database.credentials = {
    'user': environ.get('DENARO_DATABASE_USER', 'gaetano'),
    'password': environ.get('DENARO_DATABASE_PASSWORD', ''),
    'database': environ.get('DENARO_DATABASE_NAME', '')
}


async def main():
    denaro_database: Database = await Database.get()
    dvm = DVM(denaro_database)
    i = await denaro_database.get_next_block_id()
    while True:
        block = await denaro_database.get_block_by_id(i)
        if block is not None:
            block_hash = block['hash']
            i += 1
            # transactions with only one input can be filtered by the query.
            # anyway, could add possibility of multi-input (why?) by making able to provide the sender address inside the transaction message
            txs = await denaro_database.get_block_transactions(block_hash, False)
            if len(txs) == 1:
                continue
            print(i)
            calls = []
            for tx in txs:
                if isinstance(tx, CoinbaseTransaction):
                    continue
                if len(tx.inputs) != 1:
                    print('Skipping transaction because too many inputs')
                    continue
                for index, output in enumerate(tx.outputs):
                    if output.address == 'DsmArTjpJNuEBuHB2x4f14cDifdduTtu2CR1BMs1P5RcF':
                        payload = tx.message
                        # todo implement gas
                        if output.amount < 50:
                            print(f'Skipping output {index} of transaction {tx.hash()} because amount is {output.amount} denari')
                            break
                        try:
                            contract_call = ContractCall.from_payload(payload)
                        except Exception as e:
                            print('Invalid payload:', e)
                            continue
                        # fixme rename
                        contract_creation_hash = sha256(bytes.fromhex(block_hash) + bytes.fromhex(tx.hash()) + bytes([index]))
                        calls.append({
                            'contract_call': contract_call,
                            'tx_hash': tx.hash(),
                            # fixme show only if deploying a contract
                            'contract_creation_hash': contract_creation_hash,
                            'sender': point_to_string(await tx.inputs[0].get_public_key()),
                            'fees': output.amount
                        })
            contracts_hashes = [contract_call.contract_hash for contract_call in [call['contract_call'] for call in calls] if contract_call.__class__ == ContractCall]
            ContractsCache.contracts = await dvm.get_contracts(contracts_hashes, all=True)
            for call in calls:
                contract_call, tx_hash, sender = call['contract_call'], call['tx_hash'], call['sender']
                if isinstance(contract_call, ContractCreation):
                    await dvm.create_contract(contract_call, call['contract_creation_hash'], tx_hash, block['id'], sender, contract_call.args)
                else:
                    if contract_call.contract_hash not in ContractsCache.contracts:
                        print('Skipping call because contract does not exist')
                        continue
                    if contract_call.method == 'constructor':  # fixme
                        print('Cannot call constructor')
                        continue
                    state_backup = ContractsCache.contracts.copy()
                    contract = ContractsCache.contracts[contract_call.contract_hash]
                    ContractsCache.current_contract = contract
                    ContractsCache.contract_instances = [contract_call.contract_hash]
                    try:
                        contract._methods[contract_call.method](Address(sender), *contract_call.args)
                    except (Exception, KeyboardInterrupt) as e:
                        ContractsCache.contracts = state_backup
                        print(f'Transaction in contract {contract_call.contract_hash} reversed because of {e.__class__.__name__}: {str(e)}')
                    ContractsCache.current_contract = None

            updated_contract_states = {contract._contract_hash: contract.get_json_state() for contract in ContractsCache.contracts.values()}
            await dvm.update_contract_states(updated_contract_states, block['id'])
        else:
            await sleep(3)

if __name__ == '__main__':
    asyncio.run(main())

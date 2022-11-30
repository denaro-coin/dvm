from asyncio import sleep, get_event_loop
from copy import deepcopy
from decimal import Decimal
from os import environ

from denaro import Database
from denaro.constants import SMALLEST
from denaro.helpers import sha256, point_to_string
from denaro.transactions import CoinbaseTransaction, Transaction

from dvm.contract import ContractCallList, ContractCall, ContractCreation, ContractsCache, Address
from dvm.vm import DVM
from dvm.serializer import serialize
from dvm.timeout import timeout

from dvm.contract import DVMTransaction

CONTRACT_METHOD_TIMEOUT = 0.01

Database.credentials = {
    'user': environ.get('DENARO_DATABASE_USER', 'denaro'),
    'password': environ.get('DENARO_DATABASE_PASSWORD', ''),
    'database': environ.get('DENARO_DATABASE_NAME', 'denaro')
}

# it will change before the stable release
DVM_ADDRESS = 'DsmArTjpJNuEBuHB2x4f14cDifdduTtu2CR1BMs1P5RcF'


async def main():
    denaro_database: Database = await Database.get()
    dvm = DVM(denaro_database)
    i = 100_000
    async with denaro_database.pool.acquire() as connection:
        res = await connection.fetchrow('SELECT block_no FROM dvm_state ORDER BY block_no DESC LIMIT 1')
        if res:
            i = res['block_no'] + 1
    #i = 18046 - 1
    i = await denaro_database.get_next_block_id()
    while True:
        block = await denaro_database.get_block_by_id(i)
        if block is not None:
            block_hash = block['hash']
            i += 1
            # transactions with only one input can be filtered by the query.
            # a kind of multisig could be implemented by making able to use more input addresses and provide a list of them to the smart contract
            async with denaro_database.pool.acquire() as connection:
                txs = await connection.fetch('SELECT tx_hex FROM transactions WHERE block_hash = $1 AND $2 = ANY(outputs_addresses)', block_hash, DVM_ADDRESS)
            txs = [await Transaction.from_hex(tx['tx_hex'], False) for tx in txs]
            if len(txs) == 0:
                continue
            print(i)
            calls = []
            for tx in txs:
                if isinstance(tx, CoinbaseTransaction):
                    continue
                if len(set([point_to_string(await tx_input.get_public_key()) for tx_input in tx.inputs])) != 1:
                    print('Skipping transaction because too many input addresses')
                    continue
                if any(output.address == DVM_ADDRESS for output in tx.outputs):
                    payload = tx.message
                    try:
                        contract_call_list = ContractCallList.from_payload(payload)
                    except Exception as e:
                        print('Invalid payload:', e)
                        continue
                    await tx.get_fees()
                    dvm_tx = DVMTransaction(tx.hash(), tx.outputs)
                    for index, output in enumerate(tx.outputs):
                        if output.address == DVM_ADDRESS:
                            # fixme rename
                            # fixme change way it is created
                            contract_creation_hash = sha256(bytes.fromhex(block_hash) + bytes.fromhex(tx.hash()) + bytes([index]))
                            calls.append({
                                'contract_call': contract_call_list.contract_calls[index],
                                'tx_hash': tx.hash(),
                                'dvm_tx': dvm_tx,
                                'output_index': index,
                                # fixme show only if deploying a contract
                                'contract_creation_hash': contract_creation_hash,
                                'sender': point_to_string(await tx.inputs[0].get_public_key()),
                                'fees': output.amount,
                                'fee_rate': (tx.fees / len(tx.hex()) / 2) if tx.fees > 0 else (1 / Decimal(SMALLEST))
                            })
            if not calls:
                continue
            contracts_hashes = [contract_call.contract_hash for contract_call in [call['contract_call'] for call in calls] if contract_call.__class__ == ContractCall]
            #contracts_hashes.extend(['ce6dcfede06637a498554c1e5003857d7014b0cb26ea63c6d05e62d13c2ecb25', 'eeb0528554404d4a821018a6153644206a9ccf92c622421167126a02d960e8d7'])
            ContractsCache.contracts = await dvm.get_contracts(contracts_hashes)

            dvm_transactions = []
            emitted_events = []
            for call in calls:
                contract_call, tx_hash, output_index, sender = call['contract_call'], call['tx_hash'], call['output_index'], call['sender']

                state_backup = deepcopy(ContractsCache.contracts)
                ContractsCache.current_transaction = call['dvm_tx']
                ContractsCache.emitted_events = []
                ContractsCache.created_contracts = []

                if isinstance(contract_call, ContractCreation):
                    if contract := await dvm.create_contract(contract_call, call['contract_creation_hash'], tx_hash, block['id'], sender, contract_call.args):
                        pass
                    else:
                        continue
                else:
                    contract = ContractsCache.contracts[contract_call.contract_hash]
                    ContractsCache.current_contract_hash = contract_call.contract_hash
                    ContractsCache.contract_instances = [contract_call.contract_hash]
                    if contract_call.contract_hash not in ContractsCache.contracts:
                        print(f'Skipping call because contract {contract_call.contract_hash} does not exist')
                        continue
                    if contract_call.method == 'constructor':  # fixme
                        print('Cannot call constructor')
                        continue
                    if contract_call.method not in contract._methods:
                        print(f'Skipping call because contract {contract_call.contract_hash} does not have {contract_call.method} method')
                        continue
                    try:
                        timeout(CONTRACT_METHOD_TIMEOUT, contract._methods[contract_call.method], Address(sender), *contract_call.args)
                    except (Exception, KeyboardInterrupt) as e:
                        ContractsCache.contracts = state_backup
                        print(f'Transaction in contract {contract_call.contract_hash} reverted because of {e.__class__.__name__}: {str(e)}')
                        raise
                        continue

                # todo fix implementation
                """if ContractsCache.created_contracts:
                    for i, (creator_contract_hash, class_name, specifier, args, kwargs) in enumerate(ContractsCache.created_contracts):
                        source_code = (await dvm.get_contracts_source(creator_contract_hash))[creator_contract_hash]
                        source_code += f'Contract.deployed = {class_name}'
                        contract_creation = ContractCreation(specifier, source_code, ())
                        contract_creation_hash = sha256(bytes.fromhex(call['contract_creation_hash']) + bytes([i]))
                        if contract := await dvm.create_contract(contract_creation, contract_creation_hash, tx_hash, block['id'], creator_contract_hash, args, kwargs):
                            ContractsCache.contracts[contract_creation_hash] = contract"""

                state_size_delta = abs(
                    len(serialize(
                        {contract.address: contract._variables for
                         contract in state_backup.values()})) -
                    len(serialize(
                        {contract.address: contract._variables for
                         contract in ContractsCache.contracts.values()}))
                )

                print(state_size_delta, 'bytes for state change')

                if ContractsCache.emitted_events:
                    state_size_delta += len(serialize([event.to_dict() for _, event in ContractsCache.emitted_events]))
                    print(len(serialize([event.to_dict() for _, event in ContractsCache.emitted_events])), 'bytes for events')

                total_gas = state_size_delta + len(ContractsCache.contract_instances) * 1024
                fees_required = total_gas * call['fee_rate']

                if call['fees'] < fees_required:
                    ContractsCache.contracts = state_backup
                    print(total_gas, call['fee_rate'])
                    print(f'Transaction in contract {contract_call.contract_hash} reverted because of not enough gas: sent {call["fees"]} while required {fees_required}')
                    continue

                if ContractsCache.emitted_events:
                    emitted_events.extend((tx_hash, output_index, contract_hash, *event.to_tuple()) for contract_hash, event in ContractsCache.emitted_events)

                print(fees_required, contract._variables)

                dvm_transactions.append((contract._contract_hash, tx_hash, output_index, contract_call.get_payload().hex()))

            updated_contract_states = {contract.address: contract.get_json_state() for contract in ContractsCache.contracts.values()}
            await dvm.update_contract_states(updated_contract_states, block['id'])
            await dvm.add_transactions(dvm_transactions)
            await dvm.add_events(emitted_events)
        else:
            await sleep(3)

if __name__ == '__main__':
    get_event_loop().run_until_complete(main())

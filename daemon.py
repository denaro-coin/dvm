from asyncio import sleep, get_event_loop
from copy import deepcopy
from decimal import Decimal
from os import environ

from denaro import Database
from denaro.constants import SMALLEST
from denaro.helpers import sha256, point_to_string
from denaro.transactions import CoinbaseTransaction

from contract import ContractCallList, ContractCall, ContractCreation, ContractsCache, Address
from dvm import DVM
from serializer import serialize

Database.credentials = {
    'user': environ.get('DENARO_DATABASE_USER', 'denaro'),
    'password': environ.get('DENARO_DATABASE_PASSWORD', ''),
    'database': environ.get('DENARO_DATABASE_NAME', 'denaro')
}


async def main():
    denaro_database: Database = await Database.get()
    dvm = DVM(denaro_database)
    # todo save last processed block and implement reorganizations
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
                        try:
                            contract_call_list = ContractCallList.from_payload(payload)
                        except Exception as e:
                            print('Invalid payload:', e)
                            continue
                        await tx.get_fees()
                        # fixme rename
                        # fixme change way it is created
                        contract_creation_hash = sha256(bytes.fromhex(block_hash) + bytes.fromhex(tx.hash()) + bytes([index]))
                        for contract_call in contract_call_list:
                            calls.append({
                                'contract_call': contract_call,
                                'tx_hash': tx.hash(),
                                # fixme show only if deploying a contract
                                'contract_creation_hash': contract_creation_hash,
                                'sender': point_to_string(await tx.inputs[0].get_public_key()),
                                'fees': output.amount / len(contract_call_list.contract_calls),
                                'fee_rate': (tx.fees / len(tx.hex()) / 2) if tx.fees > 0 else (1 / Decimal(SMALLEST))
                            })
                        continue
            if not calls:
                continue
            contracts_hashes = [contract_call.contract_hash for contract_call in [call['contract_call'] for call in calls] if contract_call.__class__ == ContractCall]
            ContractsCache.contracts = await dvm.get_contracts(contracts_hashes, all=True)
            dvm_transactions = []
            for call in calls:
                contract_call, tx_hash, sender = call['contract_call'], call['tx_hash'], call['sender']
                if isinstance(contract_call, ContractCreation):
                    await dvm.create_contract(contract_call, call['contract_creation_hash'], tx_hash, block['id'], sender, contract_call.args)
                    dvm_transactions.append((call['contract_creation_hash'], tx_hash, contract_call.get_payload().hex(), 'constructor'))
                else:
                    if contract_call.contract_hash not in ContractsCache.contracts:
                        print(f'Skipping call because contract {contract_call.contract_hash} does not exist')
                        continue
                    if contract_call.method == 'constructor':  # fixme
                        print('Cannot call constructor')
                        continue
                    state_backup = deepcopy(ContractsCache.contracts)
                    contract = ContractsCache.contracts[contract_call.contract_hash]
                    ContractsCache.current_contract = contract
                    ContractsCache.contract_instances = [contract_call.contract_hash]
                    try:
                        contract._methods[contract_call.method](Address(sender), *contract_call.args)
                    except (Exception, KeyboardInterrupt) as e:
                        ContractsCache.contracts = state_backup
                        print(f'Transaction in contract {contract_call.contract_hash} reversed because of {e.__class__.__name__}: {str(e)}')
                        continue
                    ContractsCache.current_contract = None
                    state_size_delta = abs(
                        len(serialize(
                            {contract._contract_hash: {k: serialize(v) for k, v in contract._variables.items()} for
                             contract in state_backup.values()})) -
                        len(serialize(
                            {contract._contract_hash: {k: serialize(v) for k, v in contract._variables.items()} for
                             contract in ContractsCache.contracts.values()}))
                    )

                    total_gas = state_size_delta + len(ContractsCache.contract_instances) * 1024
                    fees_required = total_gas * call['fee_rate']

                    if call['fees'] < fees_required:
                        ContractsCache.contracts = state_backup
                        print(f'Transaction in contract {contract_call.contract_hash} reversed because of not enough gas: sent {call["fees"]} while required {fees_required}')
                        continue

                    dvm_transactions.append((contract_call.contract_hash, tx_hash, contract_call.get_payload().hex(), contract_call.method))

            updated_contract_states = {contract._contract_hash: contract.get_json_state() for contract in ContractsCache.contracts.values()}
            await dvm.update_contract_states(updated_contract_states, block['id'])
            await dvm.add_transactions(dvm_transactions)
        else:
            await sleep(3)

if __name__ == '__main__':
    get_event_loop().run_until_complete(main())

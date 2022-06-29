import sys
from decimal import Decimal
from contract import CURRENT_VERSION, ContractCall

args = sys.argv[1:]

if not args:
    print(f"Usage: python3 {sys.argv[0]} contract_hash method args")
    exit()


contract_hash, method, call_args = tuple(args)

print(ContractCall(CURRENT_VERSION, contract_hash, method, eval(call_args)).get_payload().hex())

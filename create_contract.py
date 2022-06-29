import sys
from decimal import Decimal
from contract import ContractCreation, CURRENT_VERSION

args = sys.argv[1:]

if not args:
    print(f"Usage: python3 {sys.argv[0]} file.py")
    exit()


source_code = open(args[0], 'r').read()

print(ContractCreation(CURRENT_VERSION, source_code, eval(args[1])).get_payload().hex())


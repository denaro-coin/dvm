import inspect
import json
import zlib
from io import BytesIO
from typing import Dict, List, Tuple

from denaro.constants import ENDIAN
from denaro.transactions import TransactionOutput
from dvm.serializer import serialize, deserialize

CURRENT_VERSION = b"dvm0\0"


class Address:
    def __init__(self, address: str):
        self.address = address

    def __str__(self):
        return self.address

    def __repr__(self):
        return f"Address <{self.address}>"


class Event:
    def __init__(self, *args, **kwargs):
        args_names = self.construct.__code__.co_varnames[1:self.construct.__code__.co_argcount]
        self._args = {**dict(zip(args_names, args)), **kwargs}

    def construct(self, **kwargs):
        ...

    def to_dict(self):
        return {'_': self.__class__.__name__} | self._args

    def to_tuple(self):
        return self.__class__.__name__, json.dumps({k: serialize(v).hex() for k, v in self._args.items()})


class DVMTransaction:
    def __init__(self, tx_hash: str, outputs: List[TransactionOutput]):
        self.tx_hash = tx_hash
        self.outputs = outputs
        

class ContractsCache:
    # fixme
    contracts: Dict[str, "Contract"] = {}
    contract_instances: list = []
    current_contract_hash: str = None

    current_transaction: DVMTransaction = None
    #current_block: Block = None

    emitted_events: List[Tuple[str, Event]] = []
    created_contracts: List[tuple] = []

    @staticmethod
    async def get(contract_hash):
        if contract_hash not in ContractsCache.contracts:
            raise NotImplementedError()
        return ContractsCache.contracts[contract_hash]


class Contract:
    deployed: "Contract" = None

    # todo rename sender?
    def __init__(self, contract_hash: str, variables: dict, methods: dict = None):
        self._contract_hash = contract_hash
        self._variables = variables
        self._methods = methods or {}
        self._caller_contract: Address

        if not methods:
            for name, func in inspect.getmembers(self, predicate=inspect.ismethod):
                if not func.__qualname__.startswith(self.__class__.__name__):
                    continue
                if getattr(self.__class__, name):  # the check fails for inherited classes
                    delattr(self.__class__, name)
                self.wrap(func)

    @staticmethod
    def deploy(obj):
        assert Contract.deployed is None, 'cannot deploy: already deployed'
        assert issubclass(obj, Contract), 'cannot deploy: contract does not inherit main class'
        Contract.deployed = obj
        return obj

    def reserved(self):
        return {
            'reserved': None,
            'create': None,
            'emit': None,
            'deploy': None,
            'wrap': None,

            'address': self._contract_hash,
            'transaction': ContractsCache.current_transaction,
            #'block': ContractsCache.current_block
        }

    # todo
    @classmethod
    def create(cls, *args, **kwargs):
        ContractsCache.created_contracts.append((ContractsCache.current_contract_hash, cls.__name__, CURRENT_VERSION, args, kwargs))

    def emit(self, event: Event):
        assert isinstance(event, Event), 'you can only emit instances of Event'
        ContractsCache.emitted_events.append((self._contract_hash, event))

    def wrap(self, func):
        assert (func.__name__ not in self._methods)
        if func.__code__.co_argcount - 1 > len(func.__annotations__):
            raise TypeError(f'Method {func.__name__} types must be specified')

        def wrapper(*args, **kwargs):
            func_args = inspect.getfullargspec(func).args[1:]
            if func_args and func_args[0] == 'sender':
                if args[0].__class__ != Address:
                    if self._caller_contract is not None:
                        args = (self._caller_contract, *args)
                    else:
                        raise TypeError('Sender has not been passed')
                args = (str(args[0]), *args[1:])

                print(f"calling {self._contract_hash} from {args[0]}")
            for i, arg in enumerate(args):
                should_be = list(func.__annotations__.values())[i]
                if type(arg) != should_be:
                    raise TypeError(f'Parameter {i + 1} of {func.__name__} method must be {should_be.__name__}, not {type(arg).__name__}')
            for i, (key, arg) in enumerate(kwargs.items()):
                should_be = func.__annotations__[key]
                # fixme
                from decimal import Decimal
                if type(arg) is str and should_be is Decimal:
                    kwargs[key] = Decimal(arg)
                elif type(arg) is str and should_be is int:
                    kwargs[key] = int(arg)
                elif type(arg) != should_be:
                    raise TypeError(f'Parameter {i + 1} of {func.__name__} method must be {should_be.__name__}, not {type(arg).__name__}')

            try:
                previous_contract = ContractsCache.current_contract_hash
                ContractsCache.current_contract_hash = self._contract_hash
                res = func(*args, **kwargs)
                ContractsCache.current_contract_hash = previous_contract
                return res
            except Exception:
                print('caught in ', self._contract_hash, args)
                raise
        self._methods[func.__name__] = wrapper

    def __getattr__(self, key: str):
        if key[0] == '_':
            return super(Contract, self).__getattribute__(key)
        if key in self.reserved():
            return self.reserved()[key]
        if key in self._variables:
            return self._variables[key]
        elif key in self._methods:
            return self._methods[key]
        else:
            return super(Contract, self).__getattribute__(key)

    def __setattr__(self, key: str, value):
        if key[0] == '_':
            super(Contract, self).__setattr__(key, value)
        else:
            assert key not in self._methods, f'overwriting {key} method'
            assert key not in self.reserved(), 'overwriting reserved property'
            self._variables[key] = value

    def get_payload(self, method: str, args: tuple, specifier: bytes = CURRENT_VERSION):
        return ContractCall(specifier, str(self._contract_hash), method, args).get_payload()

    def get_json_state(self):
        return json.dumps({k: serialize(v).hex() for k, v in self._variables.items()})


class ContractCall:
    def __init__(self, specifier: bytes, contract_hash: str, method: str, args: tuple = ()):
        self.specifier = specifier
        self.contract_hash = contract_hash
        self.method = method
        self.args = args

    @staticmethod
    def from_payload(payload: bytes | str):
        if isinstance(payload, str):
            payload = bytes.fromhex(payload)
        try:
            payload = zlib.decompress(payload)
        except zlib.error:
            pass
        buffer = BytesIO(payload)
        specifier = buffer.read(5)
        kind = int.from_bytes(buffer.read(1), ENDIAN)
        if kind == 0:
            source_code_length = int.from_bytes(buffer.read(2), ENDIAN)
            source_code = buffer.read(source_code_length).decode()
            args_length = int.from_bytes(buffer.read(2), ENDIAN)
            args = deserialize(buffer.read(args_length))
            return ContractCreation(specifier, source_code, args)
        contract_hash = buffer.read(32).hex()
        method_length = int.from_bytes(buffer.read(1), ENDIAN)
        method = buffer.read(method_length).decode()
        args = deserialize(buffer.read())
        return ContractCall(specifier, contract_hash, method, args)

    def get_payload(self):
        method_bytes = self.method.encode()
        args_bytes = serialize(self.args)
        return self.specifier + bytes([1]) + bytes.fromhex(self.contract_hash) + bytes(
            [len(method_bytes)]) + method_bytes + args_bytes


class ContractCreation:
    def __init__(self, specifier: bytes, source_code: str, args: tuple = tuple()):
        self.specifier = specifier
        self.source_code = source_code
        self.args = args

    def get_payload(self):
        source_code_bytes = self.source_code.encode()
        args_bytes = serialize(self.args)
        payload = self.specifier + bytes([0]) + len(source_code_bytes).to_bytes(2, ENDIAN) + source_code_bytes + len(args_bytes).to_bytes(2, ENDIAN) + args_bytes
        return zlib.compress(payload)


class ContractCallList:
    def __init__(self, contract_calls: List[ContractCall | ContractCreation]):
        self.contract_calls = contract_calls

    @staticmethod
    def from_payload(payload: bytes | str):
        if isinstance(payload, str):
            payload = bytes.fromhex(payload)
        try:
            payload = zlib.decompress(payload)
        except zlib.error:
            pass
        try:
            return ContractCallList([ContractCall.from_payload(contract_call) for contract_call in deserialize(payload)])
        except TypeError as e:
            if str(e) != 'Invalid serialized type':
                raise
            return ContractCallList([ContractCall.from_payload(payload)])

    def get_payload(self):
        return zlib.compress(serialize([contract_call.get_payload() for contract_call in self.contract_calls]))


class LimitedContract(Contract):
    _methods = {}

    def __init__(self, contract_hash: str):
        if contract_hash not in ContractsCache.contracts:
            raise NotImplementedError(f'Contract <{contract_hash}> must be present in local contracts list')
        assert contract_hash not in ContractsCache.contract_instances, 'cannot call itself'
        ContractsCache.contract_instances.append(contract_hash)
        contract = ContractsCache.contracts[contract_hash]
        contract._caller_contract = Address(ContractsCache.current_contract_hash)
        super().__init__(contract_hash, contract._variables, contract._methods)

    def export(self, func):
        raise Exception('Cannot export')

    def private(self, func):
        raise Exception('Cannot export')

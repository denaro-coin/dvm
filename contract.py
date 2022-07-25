import inspect
import json
import zlib
from io import BytesIO
from typing import Dict, List

from denaro.constants import ENDIAN
from timeout import timeout
from serializer import serialize, deserialize


CURRENT_VERSION = b"dvm0\0"

CONTRACT_METHOD_TIMEOUT = 0.001


class Address:
    def __init__(self, address: str):
        self.address = address

    def __str__(self):
        return self.address

    def __repr__(self):
        return f"Address <{self.address}>"


def _write_(obj):
    if obj.__class__ == Contract:
        return obj
    if obj.__class__ == dict:
        return obj
    raise Exception(f'Cannot write to {obj.__class__.__name__}')


class ContractsCache:
    # fixme
    contracts: Dict[str, "Contract"] = {}
    contract_instances: list = []
    current_contract: "Contract" = None

    @staticmethod
    async def get(contract_hash):
        if contract_hash not in ContractsCache.contracts:
            raise NotImplementedError()
        return ContractsCache.contracts[contract_hash]


class Contract:
    # todo rename sender?
    def __init__(self, contract_hash: str, variables: dict, methods: dict):
        self._contract_hash = contract_hash
        self._variables = variables
        self._methods = methods
        self._private_methods = methods
        self._caller_contract: Address = None

    # todo add params like no_contract, allowed_address or something?
    def export(self, func):
        assert (func.__name__ not in self._methods) and (func.__name__ not in self._private_methods)
        if func.__code__.co_argcount != len(func.__annotations__):
            raise TypeError('Method types must be specified')

        @timeout(CONTRACT_METHOD_TIMEOUT)
        def wrapper(*args, **kwargs):
            ContractsCache.current_contract = self
            func_args = inspect.getfullargspec(func).args
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
                    raise TypeError(f'Parameter {i+1} of {func.__name__} method must be {should_be.__name__}, not {type(arg).__name__}')
            for i, (key, arg) in enumerate(kwargs.items()):
                should_be = func.__annotations__[key]
                if type(arg) != should_be:
                    raise TypeError(f'Parameter {i+1} of {func.__name__} method must be {type(should_be).__name__}, not {type(arg).__name__}')

            try:
                return func(*args, **kwargs)
            except Exception as e:
                print('caught in ', self._contract_hash, args)
                raise

        self._methods[func.__name__] = wrapper
        return wrapper

    def private(self, func):
        assert (func.__name__ not in self._methods) and (func.__name__ not in self._private_methods)
        if func.__code__.co_argcount != len(func.__annotations__):
            raise TypeError('Method types must be specified')

        @timeout(CONTRACT_METHOD_TIMEOUT)
        def wrapper(*args, **kwargs):
            for i, arg in enumerate(args):
                should_be = list(func.__annotations__.values())[i]
                if type(arg) != should_be:
                    raise TypeError(f'Parameter {i+1} of {func.__name__} method must be {should_be.__name__}, not {type(arg).__name__}')
            for i, (key, arg) in enumerate(kwargs.items()):
                should_be = func.__annotations__[key]
                if type(arg) != should_be:
                    raise TypeError(f'Parameter {i+1} of {func.__name__} method must be {type(should_be).__name__}, not {type(arg).__name__}')

            try:
                return func(*args, **kwargs)
            except Exception as e:
                print(f'caught {str(e)}) in ', self._contract_hash, args)
                raise

        self._private_methods[func.__name__] = wrapper
        return wrapper

    def __getattr__(self, key: str):
        if key[0] == '_':
            return super(Contract, self).__getattribute__(key)
        if key == 'address':
            return self._contract_hash
        if key in self._variables:
            return self._variables[key]
        elif key in self._methods:
            return self._methods[key]
        elif key in self._private_methods:
            return self._private_methods[key]
        else:
            return super(Contract, self).__getattribute__(key)

    def __setattr__(self, key: str, value):
        if key[0] == '_':
            super(Contract, self).__setattr__(key, value)
        else:
            assert key not in self._methods
            assert key != 'address'
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


class ContractCallList:
    def __init__(self, contract_calls: List[ContractCall]):
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
        return serialize([contract_call.get_payload() for contract_call in self.contract_calls])

    def __iter__(self):
        return iter(self.contract_calls)


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


class LimitedContract(Contract):
    _methods = {}

    def __init__(self, contract_hash: str):
        if contract_hash not in ContractsCache.contracts:
            raise NotImplementedError()
        assert contract_hash not in ContractsCache.contract_instances, 'cannot call itself'
        ContractsCache.contract_instances.append(contract_hash)
        contract = ContractsCache.contracts[contract_hash]
        contract._caller_contract = Address(ContractsCache.current_contract._contract_hash)
        super().__init__(contract_hash, contract._variables, contract._methods)

    def export(self, func):
        raise Exception('Cannot export')

    def private(self, func):
        raise Exception('Cannot export')

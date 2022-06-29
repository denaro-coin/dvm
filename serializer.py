import io
from decimal import Decimal

from enum import Enum, auto


class Type(Enum):
    int = auto()
    str = auto()
    bytes = auto()
    Decimal = auto()
    dict = auto()
    list = auto()
    tuple = auto()
    bool = auto()  # fixme spostare bool piu in alto

    @classmethod
    def has_value(cls, value: int) -> bool:
        return value in cls._value2member_map_ 


_TYPE_TO_ENUM = {
    int: Type.int,
    str: Type.str,
    bytes: Type.bytes,
    Decimal: Type.Decimal,
    dict: Type.dict,
    list: Type.list,
    tuple: Type.tuple,
    bool: Type.bool,  # fixme anche qua
}

_TYPE_BYTE_SIZE = 1  # uint8 (0 - 255)


def type_to_bytes(value: int | str | float | dict | list | tuple):
    if type(value) not in _TYPE_TO_ENUM:
        raise TypeError(f"Type {type(value).__name__} for value {value!r} is unsupported")
    return _TYPE_TO_ENUM[type(value)].value.to_bytes(_TYPE_BYTE_SIZE, "little")


def _serialize(to: io.BytesIO, value: int | str | float | dict | list | tuple):
    to.write(type_to_bytes(value))

    match value:
        case bool():
            to.write(bytes([int(value)]))
        case int():
            length = (value.bit_length() + 7) // 8 * 2

            to.write(int.to_bytes(length, 2, "little"))  # length is a uint16
            to.write(int.to_bytes(value, length, "little", signed=True))
        case str():
            as_bytes = value.encode("utf-8")

            if len(as_bytes) > 2 ** 32 - 1:
                raise ValueError(f"String length cannot be larger than (2 ** 32 - 1)")

            _serialize(to, len(as_bytes))
            to.write(as_bytes)
        case bytes():
            if len(value) > 2 ** 32 - 1:
                raise ValueError(f"Bytes length cannot be larger than (2 ** 32 - 1)")

            _serialize(to, len(value))
            to.write(value)
        case Decimal():
            as_bytes = str(value).encode("utf-8")

            if len(as_bytes) > 2 ** 32 - 1:
                raise ValueError(f"Decimal string length cannot be larger than (2 ** 32 - 1)")

            _serialize(to, len(as_bytes))
            to.write(as_bytes)
        case dict():
            _serialize(to, len(value))
            for key, item in value.items():
                _serialize(to, key)
                _serialize(to, item)
        case list() | tuple():
            _serialize(to, len(value))
            for item in value:
                _serialize(to, item)
        case _:
            raise TypeError(f"Could not serialize {value:!r}. Reason: type {type(value).__name__} unsupported")


def _deserialize(stream: io.BytesIO):
    t = int.from_bytes(stream.read(_TYPE_BYTE_SIZE), "little")
    if not Type.has_value(t):
        print(t)
        print(stream.read().hex())
        raise TypeError("Invalid serialized type")
    match Type(t):
        case Type.int:
            length = int.from_bytes(stream.read(2), "little")
            return int.from_bytes(stream.read(length), "little", signed=True)
        case Type.str:
            length = _deserialize(stream)
            return stream.read(length).decode("utf-8")
        case Type.bool:
            return bool(int.from_bytes(stream.read(1), "little"))
        case Type.bytes:
            length = _deserialize(stream)
            return stream.read(length)
        case Type.Decimal:
            length = _deserialize(stream)
            return Decimal(stream.read(length).decode("utf-8"))
        case Type.dict:
            length = _deserialize(stream)
            result = {}

            for _ in range(length):
                key = _deserialize(stream)
                value = _deserialize(stream)
                result[key] = value

            return result
        case Type.list:
            length = _deserialize(stream)
            return [_deserialize(stream) for _ in range(length)]
        case Type.tuple:
            length = _deserialize(stream)
            return tuple(_deserialize(stream) for _ in range(length))


def deserialize(data: bytes):
    #print('ah', data)
    return _deserialize(io.BytesIO(data))


def serialize(data) -> bytes:
    to = io.BytesIO()
    _serialize(to, data)
    to.seek(0)
    return to.read()

"""
x = serialize(a := {
    "asd": {
        1: [2, (3, 6, {7: "99"})],
        "ci": {
            "add": Decimal('123.123232'),
            "radd": Decimal('987897798789.98789798778')
        }
    },
    'a': Decimal('0.9999995983475439783689275693465392875692384756')
})

print(x.hex())
print(deserialize(x))

print(a == deserialize(x))
"""

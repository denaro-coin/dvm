# DVM

DVM (Denaro Virtual Machine) is a layer built on top of Denaro Blockchain, which uses transactions messages to communicate with the VM.  

Data is stored in PostgreSQL like denaro.

**This is a very early stage and anything can change at anytime**

## installation

It will install DVM and clone denaro in DVM folder.
You can't use DVM for

```bash
git clone https://github.com/denaro-coin/dvm
cd dvm
git clone https://github.com/denaro-coin/denaro
psql -d denaro -f schema.sql
```

## usage

There are 2 parts of DVM, the "daemon" and the "server".

### daemon

The daemon scans the blockchain and processes valid DVM transactions, thus updating DVM state

```bash
python3 daemon.py
```



### server

The server is an API which servers DVM data in a readable way, enabling users and apps to read the DVM

```bash
uvicorn server:app --port 3007
```


## DVM Smart Contracts development

Smart contracts in DVM are written in Python (and this is a unique feature in crypto).

```python3
@self.export
def constructor(sender: str, name: str, ticker: str):
    self.minter = sender
    self.name = name
    self.ticker = ticker
    self.balances = {}


@self.export
def mint(sender: str, address: str, amount: Decimal):
    if sender != self.minter:
        raise Exception('Unauthorized')
    assert amount > 0
    balance = self.balances.get(address) or 0
    self.balances.update({address: balance + amount})


@self.export
def transfer(sender: str, receiver: str, amount: Decimal):
    if sender == receiver:
        raise Exception('Sender and receiver are equal')
    sender_balance = self.balances.get(sender) or 0
    if sender_balance < amount:
        raise Exception(f'Sender ({sender}) does not have enough coins (has {sender_balance} while required {amount})')
    receiver_balance = self.balances.get(receiver) or 0
    self.balances.update({sender: sender_balance - amount, receiver: receiver_balance + amount})
```

You can interact with the DVM with [cli wallet](https://github.com/denaro-coin/denaro/tree/main/denaro/wallet).

### deployment

```bash
python3 create_contract.py contract_source.py "('argument 1', 'argument 2')"
```

It will return a hex string that should be used as transaction message

```bash
denaro send -to DsmArTjpJNuEBuHB2x4f14cDifdduTtu2CR1BMs1P5RcF -d 50 -m 'HEXSTRING'
```

### calling

```bash
python3 call_contract.py contract_hash method "('argument 1', 'argument 2')"
python3 call_contract.py e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 mint "('address', Decimal('1234'))"
```

It will return a hex string that should be used as transaction message

```bash
denaro send -to DsmArTjpJNuEBuHB2x4f14cDifdduTtu2CR1BMs1P5RcF -d 50 -m 'HEXSTRING'
```
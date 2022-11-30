# DVM

DVM (Denaro Virtual Machine) is a layer built on top of Denaro Blockchain, which uses transactions messages to communicate with the VM.  

Data is stored in PostgreSQL like denaro.

**This is a very early stage and anything can change at anytime**

## installation

It will install DVM and clone denaro in DVM folder.
You can't use DVM with docker

```bash
git clone https://github.com/denaro-coin/denaro
git clone https://github.com/denaro-coin/dvm
cd dvm
ln -s ../denaro/denaro/ denaro
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
@Contract.deploy
class Token(Contract):    
    def constructor(self, sender: str, name: str, ticker: str):
        self.minter = sender
        self.name = name
        self.ticker = ticker
        self.balances = {}

    def mint(self, sender: str, address: str, amount: Decimal):
        assert sender == self.minter, 'Unauthorized'
        assert amount > 0
        balance = self.balance(address)
        self.balances.update({address: balance + amount})

    def transfer(self, sender: str, receiver: str, amount: Decimal):
        assert amount > 0, 'amount cannot be zero or lower'
        sender_balance = self.balance(sender)
        assert sender_balance >= amount, f'Sender ({sender}) does not have enough coins (has {sender_balance} while required {amount})'
        receiver_balance = self.balance(receiver)
        self.balances.update({sender: sender_balance - amount, receiver: receiver_balance + amount})

    def balance(self, address: str):
        return self.balances.get(address) or 0
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
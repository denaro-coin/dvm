@self.export
def constructor(sender: str, name: str, ticker: str):
    self.minter = sender
    self.name = name
    self.ticker = ticker
    self.balances = {}
    self.allowances = {}


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


@self.export
def allow(sender: str, receiver: str, amount: Decimal):
    if sender == receiver:
        raise Exception('Sender and receiver are equal')
    receiver_allowances = self.allowances.get(receiver) or {}
    receiver_allowance_from_sender = receiver_allowances.get(sender) or 0
    receiver_allowances[sender] = receiver_allowance_from_sender + amount
    self.allowances.update({receiver: receiver_allowances})


@self.export
def transfer_from(sender: str, send_from: str, receiver: str, amount: Decimal):
    if send_from == receiver:
        raise Exception('Sender and receiver are equal')

    sender_allowances = self.allowances.get(sender) or {}
    sender_allowance_from_send_from = sender_allowances.get(send_from) or 0
    if amount > sender_allowance_from_send_from:
        raise Exception(f'{sender} tried to transfer {amount} coins from {send_from}, while allowed only for {sender_allowance_from_send_from}')

    send_from_balance = self.balances.get(send_from) or 0
    if send_from_balance < amount:
        raise Exception(f'Send from ({send_from}) does not have enough coins (has {send_from_balance} while required {amount})')
    receiver_balance = self.balances.get(receiver) or 0
    self.balances.update({send_from: send_from_balance - amount, receiver: receiver_balance + amount})

    sender_allowances[send_from] = sender_allowance_from_send_from - amount
    self.allowances.update({sender: sender_allowances})



@self.export
def supply():
    return sum(self.balances.values())


@self.export
def get_balances():
    return self.balances


@self.export
def deposit(sender: str, amount: Decimal):
    contract = Contract('5d4261e3fc8206992f94dec1c88a0d752bfa9b65683129b8f1d508ce20c82cac')
    #contract.transfer_from(sender, self.address, amount)
    contract.deposit(amount)


@self.export
def raiser(sender: str):
    while True:
        1000 ** 100
    return 0 / 0

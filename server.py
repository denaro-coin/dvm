from fastapi import FastAPI
from starlette.requests import Request

from denaro import Database
from daemon import DVM
from contract import ContractCall

app = FastAPI()
dvm: DVM = None


@app.on_event("startup")
async def startup():
    global dvm
    denaro_database: Database = await Database.get()
    dvm = DVM(denaro_database)


@app.get("/contract/{contract_hash}/{method}")
async def call_method(contract_hash: str, method: str, request: Request):
    contracts = await dvm.get_contracts([contract_hash], all=True)
    contract = contracts[contract_hash]
    kwargs = dict(request.query_params)
    # todo remove, just for debugging purposes
    if method in contract._variables:
        return {'ok': False, "result": contract._variables[method]}
    try:
        res = contract._methods[method](**kwargs)
        return {"ok": True, "result": res}
    except Exception as e:
        raise
        return {"ok": True, "result": e.__class__.__name__}


@app.post("/get_payload/{contract_hash}/{method}")
async def call_method(contract_hash: str, method: str, request: Request):
    args = await request.json()
    return {"ok": True, "result": ContractCall(b'dmv1\0', contract_hash, method, args).get_payload().hex()}

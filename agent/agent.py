import os
from dotenv import load_dotenv
import boto3
from strands import Agent, tool
from strands.models import BedrockModel
from bedrock_agentcore import BedrockAgentCoreApp

load_dotenv()

REGION = os.getenv("AWS_REGION", "us-east-1")
MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "us.amazon.nova-micro-v1:0")
DB_NAME = os.getenv("DB_NAME", "bankdb")
CLUSTER_ARN = os.getenv("AURORA_CLUSTER_ARN")
SECRET_ARN = os.getenv("DB_SECRET_ARN")

rds = boto3.client("rds-data", region_name=REGION)


def _cell_value(cell):
    if isinstance(cell, dict):
        for k in ("doubleValue", "longValue", "intValue", "realValue", "stringValue"):
            if k in cell:
                return cell[k]
        if cell.get("isNull"):
            return None
        if "arrayValues" in cell:
            return [_cell_value(x) for x in cell["arrayValues"]]
        if "structValue" in cell:
            return cell["structValue"]
        return next(iter(cell.values()), None)
    return cell


def _exec(sql, params=None):
    resp = rds.execute_statement(
        resourceArn=CLUSTER_ARN,
        secretArn=SECRET_ARN,
        database=DB_NAME,
        sql=sql,
        parameters=params or [],
    )
    return resp.get("records", [])


def _map_account(row):
    acc = _cell_value(row[0])
    owner = _cell_value(row[1])
    curr = _cell_value(row[2])
    bal = _cell_value(row[3])
    return {
        "account_number": acc,
        "owner_name": owner,
        "currency": curr,
        "balance": float(bal) if bal is not None else None,
    }


@tool
def get_balance(account_number):
    if not CLUSTER_ARN or not SECRET_ARN:
        return {"error": "Faltan AURORA_CLUSTER_ARN o DB_SECRET_ARN."}
    rows = _exec(
        "SELECT account_number, owner_name, currency, balance "
        "FROM accounts WHERE account_number = :n",
        [{"name": "n", "value": {"stringValue": str(account_number)}}],
    )
    if not rows:
        return {"error": f"No existe la cuenta {account_number}."}
    return _map_account(rows[0])


model = BedrockModel(model_id=MODEL_ID, region=REGION, temperature=0.2)

SYSTEM = (
    "Eres un asistente bancario en español. Si el usuario quiere consultar saldo y no ha "
    "dado número de cuenta, pídelo. Cuando tengas el número, llama a get_balance y muestra "
    "número, titular, moneda y saldo. No inventes datos."
)

agent = Agent(model=model, tools=[get_balance], system_prompt=SYSTEM)
app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload):
    prompt = (payload or {}).get("prompt") or "Hola, ¿en qué te puedo ayudar?"
    result = agent(prompt)
    return {"result": result.message}


if __name__ == "__main__":
    app.run()
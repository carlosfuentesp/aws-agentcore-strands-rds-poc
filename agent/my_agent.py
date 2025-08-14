import os
import json
from dotenv import load_dotenv
import boto3
from strands import Agent, tool
from strands.models import BedrockModel
from bedrock_agentcore import BedrockAgentCoreApp

# Carga variables escritas por Terraform (null_resource deploy_agentcore)
# Espera: AWS_REGION, BEDROCK_MODEL_ID, DB_NAME, AURORA_CLUSTER_ARN, DB_SECRET_ARN
load_dotenv()

REGION = os.getenv("AWS_REGION", "us-east-1")
MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "us.amazon.nova-micro-v1:0")
DB_NAME = os.getenv("DB_NAME", "bankdb")
CLUSTER_ARN = os.getenv("AURORA_CLUSTER_ARN")
SECRET_ARN  = os.getenv("DB_SECRET_ARN")

rds = boto3.client("rds-data", region_name=REGION)

@tool
def get_balance(account_number: str) -> dict:
    """
    Consulta saldo por número de cuenta usando RDS Data API (Aurora PG Serverless v2).
    Retorna: {account_number, owner_name, currency, balance} o {error: ...}
    """
    if not (CLUSTER_ARN and SECRET_ARN):
        return {"error": "Faltan AURORA_CLUSTER_ARN o DB_SECRET_ARN."}

    resp = rds.execute_statement(
        resourceArn=CLUSTER_ARN,
        secretArn=SECRET_ARN,
        database=DB_NAME,
        sql=("SELECT account_number, owner_name, currency, balance "
             "FROM accounts WHERE account_number = :n"),
        parameters=[{"name": "n", "value": {"stringValue": account_number}}],
    )
    recs = resp.get("records", [])
    if not recs:
        return {"error": f"No existe la cuenta {account_number}."}

    row = recs[0]  # índice: 0=account_number, 1=owner_name, 2=currency, 3=balance
    # Data API puede devolver doubleValue o stringValue en numéricos según el plan
    if isinstance(row[3], dict) and "doubleValue" in row[3]:
        bal = row[3]["doubleValue"]
    elif isinstance(row[3], dict) and "stringValue" in row[3]:
        bal = float(row[3]["stringValue"])
    else:
        # fallback defensivo
        bal = float(list(row[3].values())[0])

    return {
        "account_number": row[0]["stringValue"],
        "owner_name":     row[1]["stringValue"],
        "currency":       row[2]["stringValue"],
        "balance":        bal
    }

# Modelo Bedrock
model = BedrockModel(model_id=MODEL_ID, region=REGION, temperature=0.2)

SYSTEM = (
    "Eres un asistente bancario en español. Si el usuario quiere consultar saldo y no ha "
    "dado número de cuenta, pídelo. Cuando tengas el número, llama a get_balance y muestra "
    "número, titular, moneda y saldo. No inventes datos."
)

agent = Agent(model=model, tools=[get_balance], system_prompt=SYSTEM)
app = BedrockAgentCoreApp()

@app.entrypoint
def invoke(payload: dict):
    """
    Punto de entrada para AgentCore Runtime.
    Espera JSON: { "prompt": "texto del usuario" }
    """
    user_message = (payload or {}).get("prompt") or "Hola, ¿en qué te puedo ayudar?"
    result = agent(user_message)   # result.message contiene la salida final
    return {"result": result.message}

if __name__ == "__main__":
    # Útil para pruebas locales: levanta HTTP en :8080
    app.run()
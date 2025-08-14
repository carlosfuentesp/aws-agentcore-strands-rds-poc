#!/usr/bin/env python3
import os, sys, json, uuid, argparse, subprocess, shlex
from typing import Optional
from pathlib import Path

import boto3
from botocore.config import Config

# --- cargar .env robusto (raíz del repo o búsqueda ascendente) ---
try:
    from dotenv import load_dotenv, find_dotenv
    repo_root = Path(__file__).resolve().parents[1]
    env_path = repo_root / ".env"
    loaded = False
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=False)
        loaded = True
    if not loaded:
        load_dotenv(find_dotenv(usecwd=True), override=False)
except Exception:
    pass

REGION = os.getenv("AWS_REGION", "us-east-1")
AGENT_ARN = os.getenv("AGENT_RUNTIME_ARN")

# Fallback: resolver ARN por nombre si falta
if not AGENT_ARN:
    AGENT_NAME = os.getenv("AGENT_NAME", "saldo_agent")
    try:
        cmd = (
            f"aws bedrock-agentcore-control list-agent-runtimes "
            f"--region {REGION} "
            f"--query \"agentRuntimes[?agentRuntimeName=='{AGENT_NAME}'].agentRuntimeArn\" "
            f"--output text"
        )
        out = subprocess.check_output(shlex.split(cmd), text=True).strip()
        if out and out != "None":
            AGENT_ARN = out
    except Exception:
        pass

if not AGENT_ARN:
    print("ERROR: Falta AGENT_RUNTIME_ARN (.env) y no se pudo resolver por nombre (AGENT_NAME).", file=sys.stderr)
    sys.exit(1)

client = boto3.client("bedrock-agentcore", region_name=REGION, config=Config(retries={"max_attempts": 3}))

def _extract_text_from_json(obj: dict) -> Optional[str]:
    """Extrae texto de respuestas JSON comunes del runtime."""
    res = obj.get("result", obj.get("message", obj))
    if isinstance(res, dict):
        # {"result":{"content":[{"text":"..."}]}}
        cont = res.get("content")
        if isinstance(cont, list):
            texts = [c.get("text") for c in cont if isinstance(c, dict) and c.get("text")]
            if texts:
                return "\n".join(texts)
        # {"result":{"message":{"content":[...]}}}
        msg = res.get("message")
        if isinstance(msg, dict) and isinstance(msg.get("content"), list):
            texts = [c.get("text") for c in msg["content"] if isinstance(c, dict) and c.get("text")]
            if texts:
                return "\n".join(texts)
    if isinstance(res, str):
        return res
    # fallback: algunos retornan directamente {"text": "..."}
    if obj.get("text"):
        return obj["text"]
    return None

def invoke_agent(prompt: str, session_id: str, want_stream: bool) -> str:
    payload = json.dumps({"prompt": prompt}).encode("utf-8")
    kwargs = dict(agentRuntimeArn=AGENT_ARN, runtimeSessionId=session_id, payload=payload)
    kwargs["accept"] = "text/event-stream" if want_stream else "application/json"

    resp = client.invoke_agent_runtime(**kwargs)

    # Si el servicio no devolvió SSE aunque lo pedimos, caemos a JSON
    ctype = (resp.get("contentType") or "").lower()
    is_sse = ctype.startswith("text/event-stream")

    if not is_sse:
        chunks = []
        for part in resp.get("response", []):
            if isinstance(part, (bytes, bytearray)):
                chunks.append(part.decode("utf-8", "ignore"))
            else:
                chunks.append(str(part))
        body_raw = "".join(chunks)
        try:
            body = json.loads(body_raw)
        except Exception:
            return body_raw
        text = _extract_text_from_json(body)
        return text or json.dumps(body, ensure_ascii=False)

    # --- Streaming SSE ---
    out = []
    stream = resp["response"]
    for line in stream.iter_lines():
        if not line:
            continue
        s = line.decode("utf-8", "ignore")
        if s.startswith("data: "):
            s = s[6:]

        # Algunas líneas pueden ser "event: ..." o keep-alives; ignorarlas
        if not s or s.startswith(":") or s.startswith("event:"):
            continue

        try:
            evt = json.loads(s)
        except Exception:
            # imprime crudo si no es JSON
            print(s)
            continue

        printed = False

        # 1) Campos sencillos
        for key in ("text", "delta"):
            val = evt.get(key)
            if isinstance(val, str) and val:
                print(val, end="", flush=True)
                out.append(val)
                printed = True
                break

        if printed:
            continue

        # 2) Estructura ConverseStream: contentBlockDelta.delta (string o {"text": ...})
        cbd = evt.get("contentBlockDelta")
        if isinstance(cbd, dict):
            d = cbd.get("delta")
            if isinstance(d, str) and d:
                print(d, end="", flush=True); out.append(d); printed = True
            elif isinstance(d, dict) and isinstance(d.get("text"), str):
                print(d["text"], end="", flush=True); out.append(d["text"]); printed = True
            if printed:
                continue

        # 3) Mensajes completos en un solo evento
        msg = evt.get("message")
        if isinstance(msg, dict) and isinstance(msg.get("content"), list):
            texts = [c.get("text") for c in msg["content"] if isinstance(c, dict) and c.get("text")]
            if texts:
                t = "".join(texts)
                print(t, end="", flush=True); out.append(t); printed = True

        # 4) Último recurso: result -> content[].text
        if not printed and "result" in evt:
            t = _extract_text_from_json(evt)
            if t:
                print(t, end="", flush=True); out.append(t); printed = True

        # Si no reconocimos nada, mostramos el evento para debug
        if not printed:
            # comenta la línea siguiente si no quieres eventos crudos
            # print(f"\n[evt] {json.dumps(evt, ensure_ascii=False)}\n", end="")
            pass

    print()  # salto de línea al finalizar
    return "".join(out)

def main():
    parser = argparse.ArgumentParser(description="Chat CLI para Bedrock AgentCore")
    parser.add_argument("--stream", action="store_true", help="Streaming (SSE)")
    parser.add_argument("--session", default=os.getenv("AGENT_SESSION_ID") or str(uuid.uuid4()),
                        help="ID de sesión para mantener contexto")
    args = parser.parse_args()

    # Enforce longitud mínima de sessionId (AgentCore requiere >=33)
    session_id = args.session
    if len(session_id) < 33:
        session_id = f"{session_id}-{uuid.uuid4()}"
    session_id = session_id[:64]

    print(f"Chat con runtime: {AGENT_ARN}  (region={REGION})")
    print("Comandos: /exit, /session, /new\n")

    while True:
        try:
            user = input("tú> ").strip()
            if not user:
                continue
            if user in ("/exit", "/quit"):
                break
            if user == "/session":
                print(f"(sessionId = {session_id})")
                continue
            if user == "/new":
                session_id = str(uuid.uuid4())
                print(f"(nueva sessionId = {session_id})")
                continue

            print("asistente> ", end="" if args.stream else "\n", flush=True)
            text = invoke_agent(user, session_id=session_id, want_stream=args.stream)
            if not args.stream:
                print(text)
        except KeyboardInterrupt:
            print()
            break
        except Exception as e:
            print(f"[error] {e}", file=sys.stderr)

if __name__ == "__main__":
    main()
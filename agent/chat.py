import os
import sys
import json
import uuid
import shlex
import argparse
import subprocess
from pathlib import Path

import boto3
from botocore.config import Config


def _load_env():
    try:
        from dotenv import load_dotenv, find_dotenv
        repo_root = Path(__file__).resolve().parents[1]
        env_path = repo_root / ".env"
        if env_path.exists():
            load_dotenv(dotenv_path=env_path, override=False)
        else:
            load_dotenv(find_dotenv(usecwd=True), override=False)
    except Exception:
        pass


def _run(cmd):
    try:
        out = subprocess.check_output(shlex.split(cmd), text=True)
        return out.strip()
    except Exception:
        return ""


def _resolve_agent_arn(region, explicit, name):
    if explicit:
        return explicit
    q = (
        "aws bedrock-agentcore-control list-agent-runtimes "
        f"--region {region} "
        f"--query \"agentRuntimes[?agentRuntimeName=='{name}'].agentRuntimeArn\" "
        "--output text"
    )
    arn = _run(q)
    return arn if arn and arn != "None" else ""


def _ensure_session_id(s):
    if not s:
        s = str(uuid.uuid4())
    if len(s) < 33:
        s = f"{s}-{uuid.uuid4()}"
    return s[:64]


def _cell_text_blocks(content):
    if isinstance(content, list):
        return [c.get("text") for c in content if isinstance(c, dict) and c.get("text")]
    return []


def _extract_text(obj):
    if not isinstance(obj, dict):
        return obj if isinstance(obj, str) else None
    res = obj.get("result", obj.get("message", obj))
    if isinstance(res, dict):
        texts = _cell_text_blocks(res.get("content"))
        if texts:
            return "\n".join(texts)
        msg = res.get("message")
        if isinstance(msg, dict):
            texts = _cell_text_blocks(msg.get("content"))
            if texts:
                return "\n".join(texts)
    if isinstance(res, str):
        return res
    if obj.get("text"):
        return obj["text"]
    return None


def _client(region):
    return boto3.client(
        "bedrock-agentcore",
        region_name=region,
        config=Config(retries={"max_attempts": 3}),
    )


def invoke_agent(client, agent_arn, prompt, session_id, stream):
    payload = json.dumps({"prompt": prompt}).encode("utf-8")
    kwargs = {
        "agentRuntimeArn": agent_arn,
        "runtimeSessionId": session_id,
        "payload": payload,
        "accept": "text/event-stream" if stream else "application/json",
    }
    resp = client.invoke_agent_runtime(**kwargs)
    ctype = (resp.get("contentType") or "").lower()
    is_sse = ctype.startswith("text/event-stream")

    if not is_sse:
        parts = []
        for part in resp.get("response", []):
            if isinstance(part, (bytes, bytearray)):
                parts.append(part.decode("utf-8", "ignore"))
            else:
                parts.append(str(part))
        raw = "".join(parts)
        try:
            body = json.loads(raw)
        except Exception:
            return raw
        text = _extract_text(body)
        return text or json.dumps(body, ensure_ascii=False)

    out = []
    stream_iter = resp["response"]
    for line in stream_iter.iter_lines():
        if not line:
            continue
        s = line.decode("utf-8", "ignore")
        if s.startswith("data: "):
            s = s[6:]
        if not s or s.startswith(":") or s.startswith("event:"):
            continue
        try:
            evt = json.loads(s)
        except Exception:
            print(s)
            continue

        printed = False

        for key in ("text", "delta"):
            val = evt.get(key)
            if isinstance(val, str) and val:
                print(val, end="", flush=True)
                out.append(val)
                printed = True
                break
        if printed:
            continue

        cbd = evt.get("contentBlockDelta")
        if isinstance(cbd, dict):
            d = cbd.get("delta")
            if isinstance(d, str) and d:
                print(d, end="", flush=True)
                out.append(d)
                printed = True
            elif isinstance(d, dict) and isinstance(d.get("text"), str):
                print(d["text"], end="", flush=True)
                out.append(d["text"])
                printed = True
            if printed:
                continue

        msg = evt.get("message")
        if isinstance(msg, dict) and isinstance(msg.get("content"), list):
            texts = [c.get("text") for c in msg["content"] if isinstance(c, dict) and c.get("text")]
            if texts:
                t = "".join(texts)
                print(t, end="", flush=True)
                out.append(t)
                printed = True
        if not printed and "result" in evt:
            t = _extract_text(evt)
            if t:
                print(t, end="", flush=True)
                out.append(t)
                printed = True

    print()
    return "".join(out)


def _parse_args():
    p = argparse.ArgumentParser(prog="chat_tui", description="Chat CLI para Bedrock AgentCore")
    p.add_argument("--stream", action="store_true", help="Streaming (SSE)")
    p.add_argument(
        "--session",
        default=os.getenv("AGENT_SESSION_ID") or str(uuid.uuid4()),
        help="ID de sesión para mantener contexto",
    )
    return p.parse_args()


def main():
    _load_env()
    region = os.getenv("AWS_REGION", "us-east-1")
    agent_arn = _resolve_agent_arn(region, os.getenv("AGENT_RUNTIME_ARN"), os.getenv("AGENT_NAME", "saldo_agent"))
    if not agent_arn:
        print("ERROR: Falta AGENT_RUNTIME_ARN y no se pudo resolver por nombre.", file=sys.stderr)
        sys.exit(1)

    args = _parse_args()
    session_id = _ensure_session_id(args.session)
    client = _client(region)

    print(f"Chat con runtime: {agent_arn}  (region={region})")
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
            text = invoke_agent(client, agent_arn, user, session_id, args.stream)
            if not args.stream:
                print(text)
        except KeyboardInterrupt:
            print()
            break
        except Exception as e:
            print(f"[error] {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
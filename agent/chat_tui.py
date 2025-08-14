#!/usr/bin/env python3

import os
import sys
import json
import time
import uuid
from pathlib import Path
from typing import Optional

repo_root = Path(__file__).parent.parent
env_path = repo_root / ".env"

if env_path.exists():
    from dotenv import load_dotenv
    load_dotenv(env_path)

AGENT_RUNTIME_ARN = os.getenv("AGENT_RUNTIME_ARN")
AGENT_NAME = os.getenv("AGENT_NAME", "saldo_agent")

if not AGENT_RUNTIME_ARN:
    try:
        import boto3
        client = boto3.client("bedrock-agentcore-control")
        response = client.list_agent_runtimes()
        
        for runtime in response["agentRuntimes"]:
            if runtime["agentRuntimeName"] == AGENT_NAME:
                AGENT_RUNTIME_ARN = runtime["agentRuntimeArn"]
                break
    except Exception as e:
        print(f"Error resolviendo ARN: {e}", file=sys.stderr)

if not AGENT_RUNTIME_ARN:
    print("ERROR: Falta AGENT_RUNTIME_ARN (.env) y no se pudo resolver por nombre (AGENT_NAME).", file=sys.stderr)
    sys.exit(1)

import boto3

client = boto3.client("bedrock-agentcore-runtime")

def chat_with_agent(prompt: str, session_id: Optional[str] = None) -> None:
    if not session_id:
        session_id = str(uuid.uuid4())
    
    if len(session_id) < 33:
        session_id = session_id + "x" * (33 - len(session_id))
    
    try:
        response = client.converse(
            agentId=AGENT_RUNTIME_ARN,
            sessionId=session_id,
            input={
                "text": prompt
            }
        )
        
        if "completion" in response:
            print(f"\n{response['completion']['text']}")
        else:
            print(f"\nRespuesta inesperada: {json.dumps(response, indent=2)}")
            
    except Exception as e:
        print(f"Error en chat: {e}")
        return None
    
    return session_id

def chat_with_agent_streaming(prompt: str, session_id: Optional[str] = None) -> None:
    if not session_id:
        session_id = str(uuid.uuid4())
    
    if len(session_id) < 33:
        session_id = session_id + "x" * (33 - len(session_id))
    
    try:
        response = client.converse_stream(
            agentId=AGENT_RUNTIME_ARN,
            sessionId=session_id,
            input={
                "text": prompt
            }
        )
        
        for event in response:
            if "chunk" in event:
                chunk = event["chunk"]
                
                if "bytes" in chunk:
                    try:
                        content = json.loads(chunk["bytes"].decode())
                        
                        if "result" in content and "content" in content["result"]:
                            for item in content["result"]["content"]:
                                if "text" in item:
                                    print(item["text"], end="", flush=True)
                        elif "result" in content and "message" in content["result"]:
                            message = content["result"]["message"]
                            if "content" in message:
                                for item in message["content"]:
                                    if "text" in item:
                                        print(item["text"], end="", flush=True)
                        else:
                            if "text" in content:
                                print(content["text"], end="", flush=True)
                        continue
                    except json.JSONDecodeError:
                        pass
                
                if "contentBlockDelta" in chunk:
                    delta = chunk["contentBlockDelta"]["delta"]
                    if isinstance(delta, str):
                        print(delta, end="", flush=True)
                    elif isinstance(delta, dict) and "text" in delta:
                        print(delta["text"], end="", flush=True)
                    continue
                
                if "message" in chunk:
                    message = chunk["message"]
                    if "content" in message:
                        for item in message["content"]:
                            if "text" in item:
                                print(item["text"], end="", flush=True)
                        continue
                
                if "result" in chunk and "content" in chunk["result"]:
                    for item in chunk["result"]["content"]:
                        if "text" in item:
                            print(item["text"], end="", flush=True)
                    continue
                
                print(f"\n[evt] {json.dumps(chunk, ensure_ascii=False)}\n", end="")
            
        print()
        
    except Exception as e:
        print(f"\nError en streaming: {e}")
        return None
    
    return session_id

def main():
    print("🤖 Chat con AgentCore RDS")
    print("Escribe 'quit' o 'exit' para salir")
    print("Escribe 'stream' para activar modo streaming")
    print(f"Agente: {AGENT_NAME}")
    print(f"ARN: {AGENT_RUNTIME_ARN[:50]}...")
    print("-" * 50)
    
    session_id = None
    streaming_mode = False
    
    while True:
        try:
            user_input = input("\n👤 Usuario: ").strip()
            
            if user_input.lower() in ['quit', 'exit', 'q']:
                print("👋 ¡Hasta luego!")
                break
            
            if user_input.lower() == 'stream':
                streaming_mode = not streaming_mode
                print(f"🔄 Modo streaming: {'ON' if streaming_mode else 'OFF'}")
                continue
            
            if not user_input:
                continue
            
            print("\n🤖 Agente: ", end="", flush=True)
            
            if streaming_mode:
                session_id = chat_with_agent_streaming(user_input, session_id)
            else:
                session_id = chat_with_agent(user_input, session_id)
                
        except KeyboardInterrupt:
            print("\n\n👋 ¡Hasta luego!")
            break
        except Exception as e:
            print(f"\n❌ Error: {e}")

if __name__ == "__main__":
    main()
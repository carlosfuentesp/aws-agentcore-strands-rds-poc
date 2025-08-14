# AWS AgentCore RDS POC

Proyecto de prueba de concepto para integrar AgentCore con Aurora PostgreSQL usando Data API.

## ⚠️ Configuración de Seguridad

### Archivos Sensibles (NO subir a Git)
- `infra/terraform.tfstate` - Estado de Terraform con información de AWS
- `infra/terraform.tfstate.backup` - Backup del estado
- `infra/.terraform.lock.hcl` - Lock de dependencias
- `agentcore.json` - Configuración del agente
- `agent/.bedrock_agentcore.yaml` - Configuración específica del agente
- `.env` - Variables de entorno locales

### Configuración del Agente
1. Copia `agent/.bedrock_agentcore.yaml.example` a `agent/.bedrock_agentcore.yaml`
2. Reemplaza los placeholders con tus valores:
   - `ACCOUNT_ID`: Tu ID de cuenta AWS
   - `AGENT_ID_PLACEHOLDER`: ID del agente generado
   - `SESSION_ID_PLACEHOLDER`: ID de sesión
   - `PROJECT_ID`: ID del proyecto CodeBuild

## Uso
1. Configura las credenciales de AWS
2. Ejecuta `terraform init` y `terraform apply` en el directorio `infra/`
3. Configura el agente siguiendo los pasos anteriores
4. Ejecuta el agente con `python agent/chat_tui.py`

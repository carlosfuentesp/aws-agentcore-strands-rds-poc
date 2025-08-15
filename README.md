# AWS AgentCore RDS POC

Proyecto de prueba de concepto para integrar AgentCore con Aurora PostgreSQL usando Data API.

## 🏗️ Arquitectura y Servicios AWS

### Servicios Utilizados
- **Amazon Aurora PostgreSQL Serverless v2** - Base de datos principal
- **AWS Secrets Manager** - Gestión segura de credenciales de base de datos
- **Amazon RDS Data API** - Interfaz HTTP para ejecutar SQL sin drivers
- **Amazon Bedrock AgentCore** - Runtime para agentes de IA
- **Amazon ECR** - Repositorio de contenedores para el agente
- **AWS IAM** - Roles y políticas de seguridad
- **Amazon VPC** - Red privada para la base de datos
- **AWS CodeBuild** - Construcción automática del agente

### Arquitectura
```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   AgentCore     │    │   Aurora PG      │    │  Secrets       │
│   Runtime       │◄──►│   Serverless v2  │◄──►│  Manager       │
│   (Bedrock)     │    │   + Data API     │    │  (DB Creds)    │
└─────────────────┘    └──────────────────┘    └─────────────────┘
         │                       │
         │              ┌─────────────────┐
         └──────────────►│   ECR +        │
                        │   CodeBuild     │
                        └─────────────────┘
```

## 📊 Datos Sintéticos

El sistema inserta automáticamente 5 registros de cuentas bancarias de ejemplo:

| Número de Cuenta | Propietario        | Moneda | Saldo    |
|------------------|-------------------|---------|----------|
| 100001          | Emily Johnson     | USD     | $1,250.75|
| 100002          | Carlos Ortega     | USD     | $987.10  |
| 100003          | Ana Morales       | USD     | $5,230.00|
| 100004          | Luis Fernández    | USD     | $152.42  |
| 100005          | Thomas Reyes      | USD     | $20.00   |

## 🚀 Levantamiento de Infraestructura con Terraform

### Prerrequisitos
- AWS CLI configurado con credenciales válidas
- Terraform >= 1.12.0 instalado
- Python 3.10+ para el agente

### Paso 1: Configurar AWS
```bash
# Verificar configuración de AWS
aws sts get-caller-identity

# Configurar región (opcional, por defecto us-east-1)
export AWS_REGION=us-east-1
```

### Paso 2: Inicializar Terraform
```bash
cd infra/
terraform init
```

### Paso 3: Revisar y Aplicar
```bash
# Revisar el plan de cambios
terraform plan

# Aplicar la infraestructura
terraform apply
```

**⚠️ Nota:** La primera ejecución puede tomar 10-15 minutos para crear el cluster Aurora.

### Paso 4: Verificar Recursos Creados
```bash
# Ver outputs de Terraform
terraform output

# Verificar cluster RDS
aws rds describe-db-clusters --db-cluster-identifier agentcore-rds-saldo-aurora

# Verificar secretos creados
aws secretsmanager list-secrets --query "SecretList[?contains(Name, 'agentcore-rds-saldo')]"
```

## 🤖 Configuración del Agente

### Paso 1: Configurar Archivo de Configuración
```bash
# Copiar el archivo de ejemplo
cp agent/.bedrock_agentcore.yaml.example agent/.bedrock_agentcore.yaml

# Editar con tus valores específicos
nano agent/.bedrock_agentcore.yaml
```

**Valores a reemplazar:**
- `ACCOUNT_ID`: Tu ID de cuenta AWS (ej: 343075903304)
- `AGENT_ID_PLACEHOLDER`: ID del agente generado por Terraform
- `SESSION_ID_PLACEHOLDER`: ID de sesión (se genera automáticamente)
- `PROJECT_ID`: ID del proyecto CodeBuild (se genera automáticamente)

### Paso 2: Instalar Dependencias del Agente
```bash
cd agent/
pip install -r requirements.txt
```

### Paso 3: Desplegar el Agente
```bash
# Desde el directorio agent/
agentcore configure \
  --entrypoint agent.py \
  --execution-role arn:aws:iam::ACCOUNT_ID:role/agentcore-rds-saldo-agentcore-runtime \
  --region us-east-1 \
  --name saldo_agent \
  --requirements-file requirements.txt \
  --ecr auto

# Lanzar el agente
agentcore launch \
  --env AWS_REGION=$REGION \
  --env DB_NAME=$DB_NAME \
  --env AURORA_CLUSTER_ARN="$CLUSTER_ARN" \
  --env DB_SECRET_ARN="$SECRET_ARN" \
  --env BEDROCK_MODEL_ID=amazon.nova-micro-v1:0
```

## 🧪 Pruebas desde Terminal

### Opción 1: Chat Interactivo
```bash
cd agent/
python chat.py
```

**Comandos de ejemplo:**
```
Usuario: ¿Cuál es el saldo de la cuenta 100001?
Agente: La cuenta 100001 pertenece a Emily Johnson y tiene un saldo de $1,250.75 USD.

Usuario: ¿Cuántas cuentas tienen saldo mayor a $1000?
Agente: Hay 2 cuentas con saldo mayor a $1000:
- Cuenta 100001 (Emily Johnson): $1,250.75
- Cuenta 100003 (Ana Morales): $5,230.00
```

### Opción 2: Pruebas Directas con AWS CLI
```bash
# Ejecutar consulta SQL directamente
aws rds-data execute-statement \
  --resource-arn "arn:aws:rds:us-east-1:ACCOUNT_ID:cluster:agentcore-rds-saldo-aurora" \
  --secret-arn "arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:agentcore-rds-saldo/db/master-XXXXX" \
  --database "bankdb" \
  --sql "SELECT * FROM accounts WHERE balance > 1000"
```

### Opción 3: Conectar con psql (si tienes acceso directo)
```bash
# Obtener credenciales del secret
aws secretsmanager get-secret-value \
  --secret-id "agentcore-rds-saldo/db/master" \
  --query "SecretString" \
  --output text | jq -r '.password'

# Conectar (requiere acceso a la VPC)
psql -h CLUSTER_ENDPOINT -U dbmaster -d bankdb
```

## 🧹 Limpieza y Destrucción

### Destruir Infraestructura
```bash
cd infra/
terraform destroy
```

**⚠️ Advertencia:** Esto eliminará TODOS los recursos creados, incluyendo la base de datos y los datos.

### Limpiar Archivos Locales
```bash
# Eliminar archivos generados
rm -f agentcore.json
rm -f .env
rm -f agent/.bedrock_agentcore.yaml
```

## 📝 Troubleshooting

### Problemas Comunes

**Error: "No se pudo resolver AGENT_RUNTIME_ARN"**
- Verificar que el agente se haya desplegado correctamente
- Revisar el archivo `.env` en la raíz del proyecto

**Error: "Permission denied" en RDS Data API**
- Verificar que el rol IAM tenga los permisos correctos
- Confirmar que el cluster tenga Data API habilitado

**Error: "Cluster not available"**
- Esperar a que el cluster Aurora esté completamente disponible
- Verificar logs en CloudWatch

### Logs y Monitoreo
```bash
# Ver logs del agente
aws logs describe-log-groups --log-group-name-prefix "/aws/bedrock/agentcore"

# Ver logs específicos
aws logs filter-log-events \
  --log-group-name "/aws/bedrock/agentcore/saldo_agent" \
  --start-time $(date -d '1 hour ago' +%s)000
```

## 📚 Recursos Adicionales

- [Documentación de AgentCore](https://docs.aws.amazon.com/bedrock/latest/userguide/agent-core.html)
- [RDS Data API](https://docs.aws.amazon.com/rds/latest/userguide/data-api.html)
- [Aurora Serverless v2](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/aurora-serverless-v2.html)
- [Terraform AWS Provider](https://registry.terraform.io/providers/hashicorp/aws/latest/docs)

terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws    = { source = "hashicorp/aws", version = ">= 5.55.0" }
    random = { source = "hashicorp/random", version = ">= 3.6.0" }
    null   = { source = "hashicorp/null", version = ">= 3.2.0" }
    local  = { source = "hashicorp/local", version = ">= 2.5.1" }
  }
}

provider "aws" {
  region = var.region
}

data "aws_caller_identity" "current" {}

data "aws_availability_zones" "available" {
  state = "available"
  filter {
    name   = "zone-type"
    values = ["availability-zone"]
  }
}

locals {
  # Naming
  name_prefix = var.project
  agent_name  = "saldo_agent"

  # Common tags
  common_tags = {
    Project = var.project
  }

  # Bedrock and ECR helpers
  bedrock_inference_profile_arn = "arn:aws:bedrock:${var.region}:${data.aws_caller_identity.current.account_id}:inference-profile/us.amazon.nova-micro-v1:0"
  bedrock_foundation_model_arns = [
    "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-micro-v1:0",
    "arn:aws:bedrock:us-east-2::foundation-model/amazon.nova-micro-v1:0",
    "arn:aws:bedrock:us-west-2::foundation-model/amazon.nova-micro-v1:0",
  ]
  ecr_repo_arn = "arn:aws:ecr:${var.region}:${data.aws_caller_identity.current.account_id}:repository/bedrock-agentcore-${local.agent_name}"
}

# -------------------------------
# Networking
# -------------------------------
resource "aws_vpc" "this" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-vpc"
  })
}

resource "aws_subnet" "a" {
  vpc_id            = aws_vpc.this.id
  cidr_block        = "10.0.1.0/24"
  availability_zone = data.aws_availability_zones.available.names[0]

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-subnet-a"
  })
}

resource "aws_subnet" "b" {
  vpc_id            = aws_vpc.this.id
  cidr_block        = "10.0.2.0/24"
  availability_zone = data.aws_availability_zones.available.names[1]

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-subnet-b"
  })
}

resource "aws_db_subnet_group" "this" {
  name       = "${local.name_prefix}-db-subnets"
  subnet_ids = [aws_subnet.a.id, aws_subnet.b.id]

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-db-subnets"
  })
}

resource "aws_security_group" "db" {
  name        = "${local.name_prefix}-db-sg"
  description = "Aurora security group"
  vpc_id      = aws_vpc.this.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-db-sg"
  })
}

# -------------------------------
# Secrets
# -------------------------------
resource "random_password" "db" {
  length  = 20
  special = true
}

resource "aws_secretsmanager_secret" "db_master" {
  name = "${local.name_prefix}/db/master"
  tags = local.common_tags
}

resource "aws_secretsmanager_secret_version" "db_master" {
  secret_id = aws_secretsmanager_secret.db_master.id
  secret_string = jsonencode({
    username = "dbmaster"
    password = random_password.db.result
  })
}

# -------------------------------
# Aurora PostgreSQL Serverless v2 (Data API enabled)
# -------------------------------
resource "aws_rds_cluster" "this" {
  cluster_identifier = "${local.name_prefix}-aurora"
  engine             = "aurora-postgresql"
  engine_version     = var.engine_ver
  database_name      = var.db_name

  master_username = "dbmaster"
  master_password = random_password.db.result

  

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.db.id]

  storage_encrypted                   = true
  deletion_protection                 = false
  copy_tags_to_snapshot               = true
  backup_retention_period             = 1
  iam_database_authentication_enabled = false
  skip_final_snapshot                 = true

  # RDS Data API / HTTP endpoint (supported for Aurora Postgres Serverless v2/provisioned on newer engine versions)
  enable_http_endpoint = true

  serverlessv2_scaling_configuration {
    min_capacity = var.min_acu
    max_capacity = var.max_acu
  }

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-aurora"
  })
}

resource "aws_rds_cluster_instance" "this" {
  identifier          = "${local.name_prefix}-aurora-instance-1"
  cluster_identifier  = aws_rds_cluster.this.id
  instance_class      = "db.serverless"
  engine              = aws_rds_cluster.this.engine
  engine_version      = aws_rds_cluster.this.engine_version
  publicly_accessible = false

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-aurora-instance-1"
  })
}

# -------------------------------
# IAM for Bedrock AgentCore Runtime
# -------------------------------
data "aws_iam_policy_document" "agentcore_trust" {
  version = "2012-10-17"
  statement {
    sid     = "AssumeRolePolicy"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["bedrock-agentcore.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "agentcore_runtime" {
  name               = "${local.name_prefix}-agentcore-runtime"
  assume_role_policy = data.aws_iam_policy_document.agentcore_trust.json
  tags               = local.common_tags
}

# Execution permissions

data "aws_iam_policy_document" "agentcore_policy" {
  statement {
    sid    = "SecretsRead"
    effect = "Allow"
    actions = [
      "secretsmanager:GetSecretValue",
      "secretsmanager:DescribeSecret"
    ]
    resources = [aws_secretsmanager_secret.db_master.arn]
  }

  statement {
    sid    = "RdsDataExec"
    effect = "Allow"
    actions = [
      "rds-data:ExecuteStatement",
      "rds-data:BatchExecuteStatement",
      "rds-data:BeginTransaction",
      "rds-data:CommitTransaction",
      "rds-data:RollbackTransaction"
    ]
    resources = [
      aws_rds_cluster.this.arn,
      aws_secretsmanager_secret.db_master.arn
    ]
  }

  statement {
    sid    = "Logs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents"
    ]
    resources = ["*"]
  }

  statement {
    sid       = "EcrGetAuthToken"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid    = "EcrPullBedrockAgentImage"
    effect = "Allow"
    actions = [
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchCheckLayerAvailability",
      "ecr:DescribeImages"
    ]
    resources = [local.ecr_repo_arn]
  }

  statement {
    sid    = "BedrockInvokeViaInferenceProfile"
    effect = "Allow"
    actions = [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream"
    ]
    resources = concat([local.bedrock_inference_profile_arn], local.bedrock_foundation_model_arns)
  }

  statement {
    sid       = "XRayWrites"
    effect    = "Allow"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "agentcore_inline" {
  name   = "${local.name_prefix}-agentcore-inline"
  policy = data.aws_iam_policy_document.agentcore_policy.json
}

resource "aws_iam_role_policy_attachment" "attach_agent_permissions" {
  role       = aws_iam_role.agentcore_runtime.name
  policy_arn = aws_iam_policy.agentcore_inline.arn
}

# -------------------------------
# DB seeding (via Data API)
# -------------------------------
resource "null_resource" "seed_db" {
  depends_on = [
    aws_rds_cluster_instance.this
  ]

  provisioner "local-exec" {
    interpreter = ["/bin/bash", "-lc"]
    command     = <<-EOT
      set -euo pipefail
      REGION="${var.region}"
      CLUSTER_ARN="${aws_rds_cluster.this.arn}"
      SECRET_ARN="${aws_secretsmanager_secret.db_master.arn}"
      DB="${var.db_name}"

      echo "[seed] Esperando a que el DB cluster esté 'available'..."
      aws rds wait db-cluster-available --region "$REGION" --db-cluster-identifier "${aws_rds_cluster.this.id}"

      echo "[seed] Verificando Data API..."
      aws rds describe-db-clusters --region "$REGION" --db-cluster-identifier "${aws_rds_cluster.this.id}" \
        --query "DBClusters[0].HttpEndpointEnabled" --output text | grep -qi "true"

      run_sql () {
        local SQL="$1"
        aws rds-data execute-statement \
          --region "$REGION" \
          --resource-arn "$CLUSTER_ARN" \
          --secret-arn "$SECRET_ARN" \
          --database "$DB" \
          --sql "$SQL" >/dev/null
      }

      retry () {
        local tries="$1"; shift
        local delay="$1"; shift
        local n=0
        until "$@"; do
          n=$((n+1))
          if [ $n -ge $tries ]; then
            echo "[seed] Falló tras $tries intentos"
            return 1
          fi
          echo "[seed] Reintentando en $delay s (intento $n/$tries)..."
          sleep "$delay"
        done
      }

      echo "[seed] Creando tabla si no existe..."
      retry 10 10 run_sql "CREATE TABLE IF NOT EXISTS accounts (
        account_number VARCHAR(20) PRIMARY KEY,
        owner_name     TEXT NOT NULL,
        currency       VARCHAR(3) NOT NULL DEFAULT 'USD',
        balance        NUMERIC(12,2) NOT NULL DEFAULT 0
      )"

      echo "[seed] Limpiando datos previos..."
      retry 6 5 run_sql "DELETE FROM accounts"

      echo "[seed] Insertando 5 registros..."
      insert_one () {
        local n="$1"; local o="$2"; local c="$3"; local b="$4"
        local PARAMS
        PARAMS=$(jq -n --arg n "$n" --arg o "$o" --arg c "$c" --argjson b "$b" \
          '[{name:"n",value:{stringValue:$n}},
            {name:"o",value:{stringValue:$o}},
            {name:"c",value:{stringValue:$c}},
            {name:"b",value:{doubleValue:$b}}]')
        aws rds-data execute-statement \
          --region "$REGION" \
          --resource-arn "$CLUSTER_ARN" \
          --secret-arn "$SECRET_ARN" \
          --database "$DB" \
          --sql "INSERT INTO accounts(account_number, owner_name, currency, balance) VALUES(:n,:o,:c,:b)" \
          --parameters "$PARAMS" >/dev/null
      }

      retry 6 5 insert_one "100001" "Emily Johnson"  "USD" 1250.75
      retry 6 5 insert_one "100002" "Carlos Ortega"  "USD"  987.10
      retry 6 5 insert_one "100003" "Ana Morales"    "USD" 5230.00
      retry 6 5 insert_one "100004" "Luis Fernández" "USD"  152.42
      retry 6 5 insert_one "100005" "Thomas Reyes"   "USD"   20.00

      echo "[seed] OK"
    EOT
  }

  triggers = {
    cluster = aws_rds_cluster.this.arn
    secret  = aws_secretsmanager_secret.db_master.arn
    ts      = timestamp()
  }
}

# -------------------------------
# AgentCore packaging & launch
# -------------------------------
resource "null_resource" "deploy_agentcore" {
  depends_on = [
    aws_iam_role_policy_attachment.attach_agent_permissions,
    aws_rds_cluster_instance.this,
    null_resource.seed_db
  ]

  provisioner "local-exec" {
    interpreter = ["/bin/bash", "-lc"]
    command     = <<-EOT
      set -euo pipefail

      export PATH="$HOME/.local/bin:/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:$PATH"
      export AWS_REGION="${var.region}"
      export AWS_DEFAULT_REGION="${var.region}"

      cd "${path.module}/../agent"

      cat > .env << ENV
AWS_REGION=${var.region}
DB_NAME=${var.db_name}
AURORA_CLUSTER_ARN=${aws_rds_cluster.this.arn}
DB_SECRET_ARN=${aws_secretsmanager_secret.db_master.arn}
BEDROCK_MODEL_ID=us.amazon.nova-micro-v1:0
ENV

      AGENT_NAME="${local.agent_name}"

      printf 'no\n' | agentcore configure \
        --entrypoint agent.py \
        --execution-role ${aws_iam_role.agentcore_runtime.arn} \
        --region ${var.region} \
        --name "$AGENT_NAME" \
        --requirements-file requirements.txt \
        --ecr auto

      agentcore launch

      AGC_ARN=$(aws bedrock-agentcore-control list-agent-runtimes \
        --region "${var.region}" \
        --query "agentRuntimes[?agentRuntimeName=='$AGENT_NAME'].agentRuntimeArn" \
        --output text)

      if [ -z "$AGC_ARN" ] || [ "$AGC_ARN" = "None" ]; then
        echo "No se pudo resolver el ARN con list-agent-runtimes. Dump de ayuda:"
        aws bedrock-agentcore-control list-agent-runtimes --region "${var.region}" --output json
        exit 1
      fi

      aws bedrock-agentcore-control list-agent-runtimes --region "${var.region}" \
        --output json > ../agentcore.json || true

      cd "${path.module}/.."
      printf "AWS_REGION=%s\nAGENT_RUNTIME_ARN=%s\n" "${var.region}" "$AGC_ARN" > .env
      echo "AGENT_RUNTIME_ARN=$AGC_ARN"
    EOT
  }

  triggers = {
    role_arn = aws_iam_role.agentcore_runtime.arn
    region   = var.region
    ts       = timestamp()
  }
}

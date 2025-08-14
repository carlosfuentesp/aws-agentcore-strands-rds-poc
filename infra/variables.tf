variable "project" {
  type    = string
  default = "agentcore-rds-saldo"
}

variable "region" {
  type    = string
  default = "us-east-1" # región con AgentCore preview
}

variable "db_name" {
  type    = string
  default = "bankdb"
}

variable "db_username" {
  type    = string
  default = "postgres"
}

variable "engine_ver" {
  type    = string
  default = "16.9" # Aurora PG Serverless v2 compatible con Data API
}

variable "min_acu" {
  type    = number
  default = 0 # escala a 0 (auto pause)
}

variable "max_acu" {
  type    = number
  default = 2
}
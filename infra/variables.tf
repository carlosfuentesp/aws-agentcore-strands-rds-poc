variable "project" {
  type    = string
  default = "agentcore-rds-saldo"
}

variable "region" {
  type    = string
  default = "us-east-1"
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
  default = "16.9"
}

variable "min_acu" {
  type    = number
  default = 0
}

variable "max_acu" {
  type    = number
  default = 2
}
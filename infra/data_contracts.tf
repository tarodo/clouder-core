# ── Raw data contract: quarantine and drift metrics (docs/data/contracts.md) ──
# Metric filters on the worker's structured logs; no PutMetricData grant needed.

locals {
  data_contracts_namespace = "CLOUDER/DataContracts"
}

resource "aws_cloudwatch_log_metric_filter" "quarantined_records" {
  name           = "${local.name_prefix}-quarantined-records"
  log_group_name = aws_cloudwatch_log_group.canonicalization_worker.name
  pattern        = "{ $.message = \"canonicalization_completed\" }"

  metric_transformation {
    name          = "QuarantinedRecords"
    namespace     = local.data_contracts_namespace
    value         = "$.records_quarantined"
    default_value = "0"
  }
}

resource "aws_cloudwatch_log_metric_filter" "contract_drift" {
  name           = "${local.name_prefix}-contract-drift"
  log_group_name = aws_cloudwatch_log_group.canonicalization_worker.name
  pattern        = "{ $.message = \"contract_drift\" }"

  metric_transformation {
    name      = "ContractDrift"
    namespace = local.data_contracts_namespace
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "quarantined_records" {
  alarm_name          = "${local.name_prefix}-quarantined-records"
  alarm_description   = "Raw records failed the contract and were quarantined — docs/data/contracts.md"
  namespace           = local.data_contracts_namespace
  metric_name         = "QuarantinedRecords"
  statistic           = "Sum"
  period              = 86400
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = var.alarm_sns_topic_arn != "" ? [var.alarm_sns_topic_arn] : []
  ok_actions    = var.alarm_sns_topic_arn != "" ? [var.alarm_sns_topic_arn] : []
}

resource "aws_cloudwatch_metric_alarm" "contract_drift" {
  alarm_name          = "${local.name_prefix}-contract-drift"
  alarm_description   = "Beatport records drifted from the contract (unknown, missing, re-typed or empty fields) — docs/data/contracts.md"
  namespace           = local.data_contracts_namespace
  metric_name         = "ContractDrift"
  statistic           = "Sum"
  period              = 86400
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = var.alarm_sns_topic_arn != "" ? [var.alarm_sns_topic_arn] : []
  ok_actions    = var.alarm_sns_topic_arn != "" ? [var.alarm_sns_topic_arn] : []
}

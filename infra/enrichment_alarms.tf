# ── Alerting: an enrichment vendor is out of credit ──
# Tavily and DeepSeek answer 402 Payment Required; OpenAI answers 429
# insufficient_quota. Both show up in `enrichment_vendor_error` and
# `socials_resolver_error` log events.

locals {
  enrichment_credit_log_groups = {
    label  = aws_cloudwatch_log_group.label_enricher_worker.name
    artist = aws_cloudwatch_log_group.artist_enricher_worker.name
  }
}

resource "aws_cloudwatch_log_metric_filter" "enrichment_out_of_credit" {
  for_each       = local.enrichment_credit_log_groups
  name           = "${local.name_prefix}-${each.key}-enrichment-out-of-credit"
  log_group_name = each.value
  pattern        = "?\"402 Payment Required\" ?insufficient_quota"

  metric_transformation {
    name      = "EnrichmentOutOfCredit"
    namespace = "CLOUDER/Enrichment"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "enrichment_out_of_credit" {
  alarm_name          = "${local.name_prefix}-enrichment-out-of-credit"
  alarm_description   = "An enrichment vendor (Tavily, DeepSeek, OpenAI) is out of credit — top it up"
  namespace           = "CLOUDER/Enrichment"
  metric_name         = "EnrichmentOutOfCredit"
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = local.alarm_actions
  ok_actions    = local.alarm_actions
}

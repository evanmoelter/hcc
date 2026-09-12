provider "cloudflare" {}

variable "apollo_zone_id" {
  description = "Cloudflare zone ID for Apollo's SECRET_DOMAIN."
  type        = string
  nullable    = false
}

variable "apollo_tunnel_secret" {
  description = "Base64-encoded secret containing at least 32 random bytes, supplied by the operator."
  type        = string
  sensitive   = true
  nullable    = false
}

data "cloudflare_zone" "apollo" {
  zone_id = var.apollo_zone_id
}

resource "cloudflare_zero_trust_tunnel_cloudflared" "apollo" {
  account_id    = data.sops_file.cloudflare_secrets.data["account_id"]
  name          = "apollo"
  config_src    = "local"
  tunnel_secret = var.apollo_tunnel_secret
}

resource "cloudflare_dns_record" "apollo_tunnel" {
  zone_id = var.apollo_zone_id
  name    = "external-apollo.${data.cloudflare_zone.apollo.name}"
  type    = "CNAME"
  content = "${cloudflare_zero_trust_tunnel_cloudflared.apollo.id}.cfargotunnel.com"
  proxied = true
  ttl     = 1
}

output "apollo_tunnel_alias" {
  value = cloudflare_dns_record.apollo_tunnel.name
}

output "apollo_tunnel_id" {
  value = cloudflare_zero_trust_tunnel_cloudflared.apollo.id
}

output "apollo_tunnel_credentials" {
  sensitive = true
  value = jsonencode({
    AccountTag   = data.sops_file.cloudflare_secrets.data["account_id"]
    TunnelID     = cloudflare_zero_trust_tunnel_cloudflared.apollo.id
    TunnelSecret = var.apollo_tunnel_secret
  })
}

terraform {
  required_providers {
    # cloudflare = {
    #   source  = "cloudflare/cloudflare"
    #   version = "4.28.0"
    # }
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5"
    }
    sops = {
      source  = "carlpett/sops"
      version = "1.0.0"
    }
  }
  backend "s3" {
    bucket                      = "tf-state"
    key                         = "hcc/terraform.tfstate"
    region                      = "auto"
    skip_credentials_validation = true
    skip_metadata_api_check     = true
    skip_region_validation      = true
    skip_requesting_account_id  = true
    skip_s3_checksum            = true
    use_path_style              = true
    /*
      https://github.com/hashicorp/terraform/issues/33847#issuecomment-1974231305
      ENVIRONMENT VARIABLES
      ---------------------
      AWS_ACCESS_KEY_ID     - R2 token
      AWS_SECRET_ACCESS_KEY - R2 secret
      AWS_ENDPOINT_URL_S3   - R2 location: https://ACCOUNT_ID.r2.cloudflarestorage.com
    */
  }
}

data "sops_file" "cloudflare_secrets" {
  source_file = "secret.sops.yaml"
}

provider "aws" {
  region = "wnam"

  access_key = data.sops_file.cloudflare_secrets.data["r2_access_key_id"]
  secret_key = data.sops_file.cloudflare_secrets.data["r2_secret_access_key"]

  skip_credentials_validation = true
  skip_region_validation      = true
  skip_requesting_account_id  = true

  endpoints {
    s3 = "https://${data.sops_file.cloudflare_secrets.data["account_id"]}.r2.cloudflarestorage.com"
  }
}

resource "aws_s3_bucket" "volsync" {
  bucket = "tf-hcc-volsync"
}



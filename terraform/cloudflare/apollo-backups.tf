resource "aws_s3_bucket" "apollo_volsync" {
  bucket = "tf-hcc-apollo-volsync"

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket" "apollo_cnpg" {
  bucket = "tf-hcc-apollo-cnpg"

  lifecycle {
    prevent_destroy = true
  }
}

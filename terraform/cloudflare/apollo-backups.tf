resource "aws_s3_bucket" "apollo_volsync" {
  bucket = "tf-hcc-apollo-volsync"
}

resource "aws_s3_bucket" "apollo_cnpg" {
  bucket = "tf-hcc-apollo-cnpg"
}

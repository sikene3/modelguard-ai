terraform {
  # Supply every value from a reviewed, Git-ignored backend.hcl. S3 native lockfiles are mandatory;
  # the bootstrap output provides bucket/key/Region/KMS values.
  backend "s3" {}
}

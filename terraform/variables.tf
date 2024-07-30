variable "aws_region" {
  description = "The AWS region to deploy the instance in."
  default     = "us-east-1"
}

variable "instance_type" {
  description = "The instance type to use for the instance."
  default     = "t2.micro"
}

variable "key_name" {
  description = "The name of the SSH key pair."
  type        = string
}

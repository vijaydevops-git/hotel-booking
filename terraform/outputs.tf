output "instance_ip" {
  description = "The public IP of the instance."
  value       = aws_instance.flask_app.public_ip
}

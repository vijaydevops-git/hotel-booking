provider "aws" {
  region = var.aws_region
}

resource "aws_security_group" "allow_http" {
  name_prefix = "allow_http"

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "flask_app" {
  ami           = "ami-0c55b159cbfafe1f0" # Replace with your AMI
  instance_type = var.instance_type
  key_name      = var.key_name
  security_groups = [aws_security_group.allow_http.name]

  user_data = <<-EOF
              #!/bin/bash
              sudo apt update
              sudo apt install -y python3-pip
              pip3 install flask
              sudo apt install -y git
              cd /home/ubuntu
              git clone https://github.com/vijaydevops-git/hotel-booking.git
              cd your-repo
              python3 app.py &
              EOF

  tags = {
    Name = "FlaskApp"
  }
}

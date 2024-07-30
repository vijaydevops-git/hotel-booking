# hotel-booking
# Flask Booking Application

This is a simple Flask application for a booking site.

## Prerequisites

- Python 3.x
- pip
- Terraform
- AWS CLI

## Setup

1. Clone the repository:
    ```bash
    git clone https://github.com/yourusername/your-repo.git
    cd your-repo
    ```

2. Install the dependencies:
    ```bash
    pip install -r requirements.txt
    ```

3. Run the application locally:
    ```bash
    python app.py
    ```

4. Open your browser and navigate to `http://localhost:5000`.

## Deployment on AWS

1. Navigate to the `terraform` directory:
    ```bash
    cd terraform
    ```

2. Initialize Terraform:
    ```bash
    terraform init
    ```

3. Apply the Terraform configuration:
    ```bash
    terraform apply
    ```

4. Type `yes` when prompted to confirm the plan.

5. After the instance is created, you can access the application using the public IP provided by the Terraform output.

## Note

- Replace placeholders like `ami-0c55b159cbfafe1f0`, `your-key-name`, and `https://github.com/yourusername/your-repo.git` with your actual values.
- For a production-grade setup, consider adding auto-scaling, load balancers, and database setup with AWS RDS.

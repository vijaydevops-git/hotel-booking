def get_latest_ami(ami_name, region):
    ec2 = boto3.client('ec2', region_name=region)
    
    # Define a set of regex patterns for common AMI naming conventions
    ami_patterns = [
        re.sub(r'[0-9]{8}', '*', ami_name),  # Original pattern: Matches numeric patterns like 20230418
        re.sub(r'\d{4}\.\d{1,2}\.\d{1,2}', '*', ami_name),  # Matches patterns like 2023.2.20231016
        re.sub(r'\d{4}-\d{2}-\d{2}T\d{2}-\d{2}', '*', ami_name),  # Matches patterns like 2023-10-18T10-42
        re.sub(r'\d{4}\.\d{2}\.\d{2}', '*', ami_name.split('-')[-1])  # Matches the date at the end like 2023-10-18T10-42
    ]
    
    # Fallback pattern to match similar Elastic Beanstalk AMIs
    fallback_pattern = 'aws-elasticbeanstalk-amzn-*eb_docker_amazon_linux_2-hvm-*'
    
    for pattern in ami_patterns + [fallback_pattern]:
        try:
            response = ec2.describe_images(
                Owners=['amazon'],
                Filters=[{'Name': 'name', 'Values': [pattern]}]
            )

            images = sorted(response['Images'], key=lambda x: datetime.strptime(x['CreationDate'], '%Y-%m-%dT%H:%M:%S.%fZ'), reverse=True)
            if images:
                latest_ami_info = images[0]
                return (latest_ami_info['ImageId'], latest_ami_info['Name'])  # Returning a tuple with the AMI ID and AMI name
        except Exception as e:
            continue  # If there's an error with one pattern, try the next one

    # If no suitable AMI found after all patterns
    return ("Error: No suitable AMI found. AMI might be too old or unable to get the correct pattern.", "Error: No suitable AMI name available.")

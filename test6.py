#!/opt/homebrew/bin/python3
import boto3
from datetime import datetime
import re
import csv

# Initialize clients
ec2 = boto3.client('ec2')
ssm = boto3.client('ssm')
autoscaling = boto3.client('autoscaling')

def add_to_csv(column_name, value, row_number, data_store):
    if row_number not in data_store:
        data_store[row_number] = {}
    if column_name in data_store[row_number]:
        data_store[row_number][column_name] += ' ' + str(value)
    else:
        data_store[row_number][column_name] = str(value)

def generateCSV(filename, data_store):
    # Determine the order of column headers
    columns_order = []
    for row_number in sorted(data_store.keys()):
        for column in data_store[row_number]:
            if column not in columns_order:
                columns_order.append(column)
                
    # Write to CSV using the determined order of columns
    with open(filename, 'w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=columns_order)
        writer.writeheader()
        for row_number in sorted(data_store.keys()):
            writer.writerow(data_store[row_number])

def agedifference(start_date, end_date):
    start_date = datetime.strptime(start_date.split('.')[0], '%Y-%m-%dT%H:%M:%S')
    end_date = datetime.strptime(end_date.split('.')[0], '%Y-%m-%dT%H:%M:%S')
    return (start_date - end_date).days

def get_latest_ami(ami_name, region):
    ec2_region = boto3.client('ec2', region_name=region)
    ami_name_pattern = re.sub(r'[0-9]{8}', '*', ami_name)
    try:
        response = ec2_region.describe_images(
            Owners=['amazon'],
            Filters=[{'Name': 'name', 'Values': [ami_name_pattern]}]
        )
        images = sorted(response['Images'], key=lambda x: datetime.strptime(x['CreationDate'], '%Y-%m-%dT%H:%M:%S.%fZ'), reverse=True)
        if images:
            latest_ami_info = images[0]
            return latest_ami_info['ImageId'], latest_ami_info['Name'], latest_ami_info['CreationDate']
        else:
            return "Error: AMI might be too old or unable to get correct pattern.", "N/A", "N/A"
    except Exception as e:
        return f"Error: Unable to get the latest AMI information. {str(e)}", "N/A", "N/A"

def check_patch_status(instance_id, region, row, data_store):
    try:
        patch_state = ssm.describe_instance_patch_states(InstanceIds=[instance_id])
        if patch_state['InstancePatchStates']:
            patch_group = patch_state['InstancePatchStates'][0]['PatchGroup']
            if patch_state['InstancePatchStates'][0]['InstalledPendingRebootCount'] > 0:
                add_to_csv('Patch Status', 'Non-Compliant', row, data_store)
                add_to_csv('Patch required action', 'Reboot required for patches to apply', row, data_store)
            else:
                add_to_csv('Patch Status', 'Compliant', row, data_store)
                add_to_csv('Patch required action', 'Patches are applied', row, data_store)
        else:
            add_to_csv('Patch Status', 'Compliant', row, data_store)
            add_to_csv('Patch required action', '', row, data_store)
    except Exception as e:
        add_to_csv('Patch Status', f'Error: {str(e)}', row, data_store)
        add_to_csv('Patch required action', '', row, data_store)

def check_tags(instance_id, region, row, required_tags, data_store):
    try:
        instance_tags = ec2.describe_tags(Filters=[
            {'Name': 'resource-type', 'Values': ['instance']},
            {'Name': 'resource-id', 'Values': [instance_id]}
        ])['Tags']
        instance_tags_keys = {tag['Key'] for tag in instance_tags}
        missing_tags = required_tags - instance_tags_keys
        if missing_tags:
            add_to_csv('Tags missing', ', '.join(missing_tags), row, data_store)
    except Exception as e:
        add_to_csv('Tags missing', f'Error: {str(e)}', row, data_store)

def get_instance_details():
    instances = ec2.describe_instances()
    row = 2
    required_tags = {'company-ssm-managed-patch-install-reboot', 'company:ssm:managed-qualys-install-linux', 'company:ssm:managed-crowdstrike-install', 'company-ssm-managed-scan'}
    for reservation in instances['Reservations']:
        for instance in reservation['Instances']:
            instance_id = instance['InstanceId']
            instance_name = next((tag['Value'] for tag in instance.get('Tags', []) if tag['Key'] == 'Name'), "N/A")
            instance_state = instance['State']['Name']
            region = instance['Placement']['AvailabilityZone'][:-1]
            ami_id = instance['ImageId']

            ami_response = ec2.describe_images(ImageIds=[ami_id])
            if ami_response['Images']:
                ami = ami_response['Images'][0]
                ami_name = ami.get('Name', 'N/A')
                ami_creation_date = ami['CreationDate']
                ami_age = agedifference(datetime.now().strftime('%Y-%m-%dT%H:%M:%S'), ami_creation_date)
                ami_visibility = "Public" if ami['Public'] else "Private"
            else:
                ami_name = "AMI not found"
                ami_creation_date = "N/A"
                ami_age = "N/A"
                ami_visibility = "N/A"

            asg_name = "N/A"
            asg_response = autoscaling.describe_auto_scaling_instances(InstanceIds=[instance_id])
            if asg_response['AutoScalingInstances']:
                asg_name = asg_response['AutoScalingInstances'][0]['AutoScalingGroupName']

            latest_ami_id, latest_ami_name, latest_ami_creation_date = get_latest_ami(ami_name, region)
            latest_ami_age = agedifference(datetime.now().strftime('%Y-%m-%dT%H:%M:%S'), latest_ami_creation_date)

            add_to_csv("Instance ID", instance_id , row, data_store)
            add_to_csv("Instance Name", instance_name , row, data_store)
            add_to_csv("State", instance_state , row, data_store)
            add_to_csv("Region", region , row, data_store)
            add_to_csv("Current AMI Name", ami_name , row, data_store)
            add_to_csv("Current AMI ID",  ami_id , row, data_store)
            add_to_csv("Latest AMI ID", latest_ami_id , row, data_store)
            add_to_csv("Latest AMI Name", latest_ami_name , row, data_store)
            add_to_csv("Latest AMI Creation Date", latest_ami_creation_date , row, data_store)
            add_to_csv("AMI Age in days", ami_age , row, data_store)
            add_to_csv("AMI Visibility", ami_visibility, row, data_store)
            add_to_csv("ASG Name",  asg_name , row, data_store)
            add_to_csv("Timestamp", datetime.now().strftime('%Y-%m-%d %H:%M:%S'), row, data_store)

            if latest_ami_age > 59:
                add_to_csv("Notes", "Action required to update to latest AMI", row, data_store)

            check_patch_status(instance_id, region, row, data_store)
            check_tags(instance_id, region, row, required_tags, data_store)

            print(f"Instance ID: {instance_id}")
            print(f"Instance Name: {instance_name}")
            print(f"State: {instance_state}")
            print(f"Region: {region}")
            print(f"Current AMI Name: {ami_name}")
            print(f"Current AMI ID: {ami_id}")
            print(f"Latest AMI ID: {latest_ami_id}")
            print(f"Latest AMI Name: {latest_ami_name}")
            print(f"Latest AMI Creation Date: {latest_ami_creation_date}")
            print(f"AMI Age: {ami_age} days")
            print(f"AMI Visibility: {ami_visibility}")
            print(f"ASG Name: {asg_name}")
            print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            if latest_ami_age > 59:
                print("Notes: Action required to update to latest AMI")
            print("------")

            row += 1

#### #### #### #### #### #### #### #### #### #### #### #### 
#### #### #### #### #### #### #### #### #### #### #### #### 
#### #### ####      Main Code Starts here     #### #### #### 
#### #### #### #### #### #### #### #### #### #### #### #### 
#### #### #### #### #### #### #### #### #### #### #### #### 

# This dictionary will act as an associative array to store our data
data_store = {}
row=0

get_instance_details()

# Generate CSV with dynamic filename
account_id = boto3.client('sts').get_caller_identity().get('Account')
timestamp = datetime.now().strftime('%d%B%Y_%H%M%S')
filename = f"{account_id}_Report_{timestamp}.csv"
generateCSV(filename, data_store)

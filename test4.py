import os
import subprocess
import sys
import csv
import datetime
import boto3
import re
import json
from dateutil import parser
import argparse
import shutil

# Function to check if required commands are installed
def check_commands(*cmds):
    for cmd in cmds:
        if not shutil.which(cmd):
            print(f"ERROR: {cmd} is required but it's not installed. Aborting.")
            sys.exit(1)

# Function to calculate the difference in days between two dates
def agedifference(start_date_str, end_date_str):
    try:
        start_date = parser.parse(start_date_str)
        end_date = parser.parse(end_date_str)
        difference = (start_date - end_date).days
        return f"{difference} days"
    except Exception as e:
        print(f"Error: {e}")
        return

# Function to check if the AWS session is alive
def is_session_alive():
    if not (os.getenv('AWS_ACCESS_KEY_ID') and os.getenv('AWS_SECRET_ACCESS_KEY') and os.getenv('AWS_SESSION_TOKEN')):
        return False

    try:
        session_info = subprocess.check_output(['alks', 'session', 'ls'], stderr=subprocess.DEVNULL).decode('utf-8')
        session_info = re.sub(r'\x1B\[[0-9;]*[a-zA-Z]', '', session_info)  # Remove ANSI escape sequences
        session_lines = session_info.splitlines()

        for line in session_lines:
            if 'IAM' in line:
                access_key = line.split()[0].replace('*', '')
                secret_key = line.split()[1].replace('*', '').replace('…', '')
                break
        else:
            return False

        if os.getenv('AWS_ACCESS_KEY_ID').endswith(access_key) and os.getenv('AWS_SECRET_ACCESS_KEY').endswith(secret_key):
            return True
    except Exception as e:
        print(f"Error checking session: {e}")

    return False

# Function to add or update column positions
column_positions = {}
csv_data = {}

def add_column(col_name, position=None):
    if position is None:
        position = len(column_positions) + 1

    for key in column_positions:
        if column_positions[key] >= position:
            column_positions[key] += 1

    column_positions[col_name] = position
    header_key = (1, position)
    csv_data[header_key] = col_name

# Function to add data to CSV
def add_to_csv(row, col_name, data):
    if col_name not in column_positions:
        add_column(col_name)

    col = column_positions[col_name]
    key = (row, col)

    if key in csv_data:
        csv_data[key] += f" {data}"
    else:
        csv_data[key] = data

# Function to generate CSV
def generate_csv(aws_account):
    dt = datetime.datetime.now().strftime("%d%B%Y_%H%M%S")
    filename = f"{aws_account}Report_{dt}.csv"

    with open(filename, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        max_row = max(key[0] for key in csv_data.keys())
        max_col = max(key[1] for key in csv_data.keys())

        for i in range(1, max_row + 1):
            row = [csv_data.get((i, j), '') for j in range(1, max_col + 1)]
            writer.writerow(row)

    print(f"\n\n\t\t The CSV file report is generated in  >>> {filename} <<< \n\n")

# Function to check all required tags for an instance
def chk_all_tags(tocheckinstance, tocheckregion, row, tags_to_be_checked):
    client = boto3.client('ec2', region_name=tocheckregion)
    response = client.describe_tags(Filters=[
        {'Name': 'resource-type', 'Values': ['instance']},
        {'Name': 'resource-id', 'Values': [tocheckinstance]}
    ])

    tags = {tag['Key']: tag['Value'] for tag in response['Tags']}
    missing_tags = [tag for tag in tags_to_be_checked if tag not in tags]

    for tag in missing_tags:
        add_to_csv(row, 'Tags missing', f"Missing: {tag}")

# Function to check a specific tag
def check_special_tag(tocheckinstance, tocheckregion, tagcheck):
    client = boto3.client('ec2', region_name=tocheckregion)
    response = client.describe_tags(Filters=[
        {'Name': 'resource-type', 'Values': ['instance']},
        {'Name': 'resource-id', 'Values': [tocheckinstance]},
        {'Name': 'key', 'Values': [tagcheck]}
    ])
    return len(response['Tags']) > 0

# Function to check the patch status of an instance
def check_patch_status(tocheckinstance, tocheckregion, row):
    client = boto3.client('ssm', region_name=tocheckregion)
    response = client.describe_instance_patch_states(InstanceIds=[tocheckinstance])
    patch_state = response['InstancePatchStates'][0]

    installed_pending_reboot_count = patch_state['InstalledPendingRebootCount']
    missing_count = patch_state['MissingCount']

    if installed_pending_reboot_count == 0 and missing_count == 0:
        add_to_csv(row, 'Patch Status', 'Compliant')
        add_to_csv(row, 'Patch required action', 'Patches are applied')
    else:
        if installed_pending_reboot_count > 0:
            if check_special_tag(tocheckinstance, tocheckregion, "coxauto-ssm-managed-patch-install-reboot"):
                add_to_csv(row, 'Tags missing', "coxauto-ssm-managed-patch-install-reboot")
            else:
                add_to_csv(row, 'Tags missing', "Required TAG missing: coxauto-ssm-managed-patch-install-reboot.")

        if missing_count > 0:
            add_to_csv(row, 'Patch Status', 'Non-Compliant')
            add_to_csv(row, 'Patch required action', 'Patches are required to be applied')

# Function to check the AMI status of an instance
def check_instance_ami(tocheckinstance, tocheckregion, row):
    ec2 = boto3.client('ec2', region_name=tocheckregion)
    instance_details = ec2.describe_instances(InstanceIds=[tocheckinstance])
    instance = instance_details['Reservations'][0]['Instances'][0]
    ami_id = instance['ImageId']
    ami_details = ec2.describe_images(ImageIds=[ami_id])['Images'][0]

    ami_name = ami_details['Name']
    is_public = ami_details['Public']
    creation_date = ami_details['CreationDate']

    add_to_csv(row, 'Current AMI-name', ami_name)
    add_to_csv(row, 'Current AMI-ID', ami_id)
    add_to_csv(row, 'AMI_Visibility', 'Public' if is_public else 'Private')
    add_to_csv(row, 'AMI creation date', creation_date)

    if not is_public:
        return

    ami_name_pattern = re.sub(r'\d{8}', '*', ami_name)
    latest_ami_info = ec2.describe_images(
        Owners=['amazon'],
        Filters=[{'Name': 'name', 'Values': [ami_name_pattern]}]
    )['Images']

    if not latest_ami_info:
        add_to_csv(row, 'AMI update suggestion', 'Error: Unable to get the latest AMI information.')
        return

    latest_ami_info = sorted(latest_ami_info, key=lambda x: x['CreationDate'], reverse=True)[0]
    latest_ami_name = latest_ami_info['Name']
    latest_ami_id = latest_ami_info['ImageId']
    latest_ami_date = latest_ami_info['CreationDate']

    add_to_csv(row, 'Latest AMI-ID', latest_ami_id)
    add_to_csv(row, 'Latest AMI creation date', latest_ami_date)

    if creation_date == latest_ami_date:
        add_to_csv(row, 'AMI update suggestion', 'Already at Latest')
        add_to_csv(row, 'AMI age', 'No Difference')
    else:
        age_diff = agedifference(latest_ami_date, creation_date)
        add_to_csv(row, 'AMI update suggestion', latest_ami_name)
        add_to_csv(row, 'AMI age', age_diff)

# Main function
def main():
    print("\t\tWelcome to PatchManager Checks ...")
    print('''
     _|_|_|                _|                _|              _|_|_|  _|                            _|                            
     _|    _|    _|_|_|  _|_|_|_|    _|_|_|  _|_|_|        _|        _|_|_|      _|_|      _|_|_|  _|  _|      _|_|    _|  _|_|  
     _|_|_|    _|    _|    _|      _|        _|    _|      _|        _|    _|  _|_|_|_|  _|        _|_|      _|_|_|_|  _|_|      
     _|        _|    _|    _|      _|        _|    _|      _|        _|    _|  _|        _|        _|  _|    _|        _|        
     _|          _|_|_|      _|_|    _|_|_|  _|    _|        _|_|_|  _|    _|    _|_|_|    _|_|_|  _|    _|    _|_|_|  _|        
    ''')

    parser = argparse.ArgumentParser(description='PatchManager Checks')
    parser.add_argument('-e', '--environment', required=True, help='Specify the environment (prod or non-prod)')
    parser.add_argument('-a', '--aws-account', required=True, help='Specify the AWS account ID example awsaccount2 awsaccount')

    args = parser.parse_args()

    env = args.environment
    aws_account = args.aws_account

    if env == 'non-prod' and not aws_account.endswith('np'):
        aws_account += 'np'

    check_commands('aws', 'jq', 'alks', 'sed', 'awk', 'grep')
    print("Checking if essential commands are installed:\t[ OK ]")

    try:
        account_output = subprocess.check_output(['alks', 'developer', 'accounts'], stderr=subprocess.DEVNULL).decode('utf-8')
        print(f"Account Output:\n{account_output}")  # Debugging line to print account output
        account_lines = account_output.splitlines()
        for line in account_lines:
            if aws_account in line and 'ALKSAdmin' in line:
                account_parts = line.split()
                account = f"{account_parts[1]} {account_parts[2]} {account_parts[3]}"
                print(f"Matched Account: {account}")  # Debugging line to print matched account
                break
        else:
            print(f"Error: Could not find account information for {aws_account}")
            sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"Error: Failed to get account information - {e}")
        sys.exit(1)

    print(f"Checking AWS session for {account} and Admin")

    if not is_session_alive():
        print("[ Error ] AWS session has expired. Now trying to get sessions.")
        try:
            subprocess.call(['alks', 'sessions', 'open', '-a', account, '-r', 'Admin'], stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError as e:
            print(f"Error: Failed to open session - {e}")
            sys.exit(1)
        if not is_session_alive():
            print(f"[ Error ] Possibly you do not have access to {aws_account} as Admin. Admin access is needed to perform Patch checking.")
            sys.exit(1)

    add_column('InstanceID', 1)
    add_column('Instance Name', 2)
    add_column('Instance State', 3)
    add_column('Region', 4)
    add_column('Patch Status', 5)
    add_column('Patch required action', 6)
    add_column('Tags missing', 7)
    add_column('Current AMI-name', 8)
    add_column('Current AMI-ID', 9)
    add_column('AMI_Visibility', 10)
    add_column('AMI update suggestion', 11)
    add_column('Latest AMI-ID', 12)
    add_column('Latest AMI creation date', 13)
    add_column('AMI age', 14)
    add_column('ASG Name', 15)
    add_column('Notes', 16)

    row = 2

    ec2_client = boto3.client('ec2')
    regions = ['us-east-1', 'us-west-2', 'us-west-1']

    for ec2region in regions:
        response = ec2_client.describe_instances(Filters=[{'Name': 'instance-state-name', 'Values': ['running', 'stopped']}], RegionName=ec2region)
        for reservation in response['Reservations']:
            for instance in reservation['Instances']:
                instance_id = instance['InstanceId']
                instance_name = next(tag['Value'] for tag in instance['Tags'] if tag['Key'] == 'Name')
                state = instance['State']['Name']

                add_to_csv(row, 'InstanceID', instance_id)
                add_to_csv(row, 'Instance Name', instance_name)
                add_to_csv(row, 'Region', ec2region)

                if state == 'running':
                    add_to_csv(row, 'Instance State', 'Running')
                    check_patch_status(instance_id, ec2region, row)
                    tags_to_be_checked = [
                        "coxauto-ssm-managed-patch-install-reboot",
                        "coxauto:ssm:managed-qualys-install-linux",
                        "coxauto:ssm:managed-crowdstrike-install",
                        "coxauto-ssm-managed-scan"
                    ]
                    chk_all_tags(instance_id, ec2region, row, tags_to_be_checked)
                    check_instance_ami(instance_id, ec2region, row)
                    row += 1
                elif state == 'stopped':
                    add_to_csv(row, 'Instance State', 'Stopped')
                    row += 1

    generate_csv(aws_account)
    print("Now Generating CSV .. ")

if __name__ == "__main__":
    main()

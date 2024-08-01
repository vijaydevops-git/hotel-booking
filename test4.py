import os
import subprocess
import argparse
import csv
from datetime import datetime
import boto3
import json

# Function to check if commands are available
def check_commands(commands):
    for cmd in commands:
        if not shutil.which(cmd):
            print(f"ERROR: {cmd} is required but it's not installed. Aborting.")
            exit(1)

# Function to calculate the difference in days
def agedifference(start_date, end_date):
    try:
        start_date = datetime.strptime(start_date.split('.')[0], "%Y-%m-%dT%H:%M:%S")
        end_date = datetime.strptime(end_date.split('.')[0], "%Y-%m-%dT%H:%M:%S")
        return (start_date - end_date).days
    except Exception as e:
        print(f"Date Error: {e}")
        return None

# Function to add or update column positions
def add_column(col_name, position=None):
    if position is None:
        position = len(column_positions) + 1

    if col_name in column_positions:
        return

    if position in column_positions.values():
        for key, pos in column_positions.items():
            if pos >= position:
                column_positions[key] += 1

    column_positions[col_name] = position
    csv_data[(1, position)] = col_name

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

# Function to generate CSV file
def generate_csv(aws_account):
    dt = datetime.now().strftime("%d%B%Y_%H%M%S")
    filename = f"{aws_account}Report_{dt}.csv"
    
    max_row = max(key[0] for key in csv_data.keys())
    max_col = max(key[1] for key in csv_data.keys())

    with open(filename, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        for row in range(1, max_row + 1):
            line = [csv_data.get((row, col), "") for col in range(1, max_col + 1)]
            writer.writerow(line)
    
    print(f"\n\n\t\t The CSV file report is generated in  >>> {filename} <<< \n\n")

# Function to check all required tags for an instance
def chkalltags(tocheckinstance, tocheckregion, row, env):
    tags_to_check = TagstobeCheckedNONProd if env == 'non-prod' else TagstobeCheckedProd
    client = boto3.client('ec2', region_name=tocheckregion)
    tags = client.describe_tags(Filters=[{'Name': 'resource-id', 'Values': [tocheckinstance]}, {'Name': 'resource-type', 'Values': ['instance']}])

    for tag in tags_to_check:
        if not any(t['Key'] == tag for t in tags['Tags']):
            print(f"\tError: Tag missing {tag}")
            add_to_csv(row, 'Tags missing', f"Missing: {tag}")

# Function to check patch status
def check_patch_status(tocheckinstance, tocheckregion, row):
    print("Checking on Patches:")
    client = boto3.client('ssm', region_name=tocheckregion)
    patch_states = client.describe_instance_patch_states(InstanceIds=[tocheckinstance])

    if not patch_states['InstancePatchStates']:
        print(f"\tError: No patch state found for instance {tocheckinstance}")
        return

    patch_state = patch_states['InstancePatchStates'][0]
    if patch_state['InstalledPendingRebootCount'] > 0:
        print(f"\tError: InstalledPendingRebootCount issue Non-Compliant: This instance needs to rebooted for the patches to be applied.")
        add_to_csv(row, 'Tags missing', "awsnamecompany-ssm-managed-patch-install-reboot")

    if patch_state['MissingCount'] > 0:
        print(f"\tError: MissingCount. Non-Compliant: Patches are not applied, This instance need urgent attention.")
        add_to_csv(row, 'Patch required action', "Patches are required to be applied")
        add_to_csv(row, 'Patch Status', "Non-Compliant")
    else:
        add_to_csv(row, 'Patch required action', "Patches are applied")
        add_to_csv(row, 'Patch Status', "Compliant")
        print(f"\t All patches applied and instance is Compliant [ OK ]")

# Function to check instance AMI
def check_instance_ami(tocheckinstance, tocheckregion, row):
    client = boto3.client('ec2', region_name=tocheckregion)
    instance_details = client.describe_instances(InstanceIds=[tocheckinstance])
    ami_id = instance_details['Reservations'][0]['Instances'][0]['ImageId']
    ami_details = client.describe_images(ImageIds=[ami_id])['Images'][0]

    ami_name = ami_details['Name']
    is_public = ami_details['Public']
    creation_date = ami_details['CreationDate']

    print(f"\tCurrent AMI Name: {ami_name}")
    add_to_csv(row, "Current AMI-name", ami_name)
    print(f"\tPublic: {is_public}")
    print(f"\tAMI ID: {ami_id}")
    add_to_csv(row, "Current AMI-ID", ami_id)
    print(f"\tCreation Date: {creation_date}")
    add_to_csv(row, "Latest AMI creation date", creation_date)

    asg = client.describe_auto_scaling_instances(InstanceIds=[tocheckinstance])['AutoScalingInstances']
    if asg:
        print(f"\tPart of Auto Scaling Group: Yes ({asg[0]['AutoScalingGroupName']})")
        add_to_csv(row, "ASG Name", asg[0]['AutoScalingGroupName'])
    else:
        print("\tPart of Auto Scaling Group: No")
        add_to_csv(row, "ASG Name", "Not in ASG")

    if not is_public:
        print("\tThe AMI is private. No further checks.")
        add_to_csv(row, "AMI_Visibility", "Private")
        return

    print("\tThe AMI is Public.")
    add_to_csv(row, "AMI_Visibility", "Public")

    ami_name_pattern = ami_name[:ami_name.rfind('-') + 1] + '*'
    latest_ami_info = client.describe_images(Owners=['amazon'], Filters=[{'Name': 'name', 'Values': [ami_name_pattern]}], Query={'Images': ['Images']}['CreationDate']).sort(key=lambda x: x['CreationDate'], reverse=True)

    if not latest_ami_info:
        print("\tError: Unable to get the latest AMI information.")
        add_to_csv(row, "AMI update suggestion", "Error: Unable to get the latest AMI information.")
        return

    latest_ami = latest_ami_info[0]
    latest_ami_name = latest_ami['Name']
    latest_ami_id = latest_ami['ImageId']
    latest_ami_date = latest_ami['CreationDate']

    print(f"\tLatest AMI Name: {latest_ami_name}")
    print(f"\tLatest AMI ID: {latest_ami_id}")
    add_to_csv(row, "Latest AMI-ID", latest_ami_id)
    print(f"\tLatest AMI creation date: {latest_ami_date}")
    add_to_csv(row, "Latest AMI creation date", latest_ami_date)

    if creation_date == latest_ami_date:
        print("\tThe AMI is the latest.")
        add_to_csv(row, "AMI update suggestion", "Already at Latest")
        add_to_csv(row, "AMI age", "No Difference")
    else:
        print("\tThe AMI is not the latest.")
        add_to_csv(row, "AMI update suggestion", latest_ami_name)
        age_diff = agedifference(latest_ami_date, creation_date)
        print(f"\tAge difference: {age_diff} days")
        add_to_csv(row, "AMI age", f"{age_diff} days")

# Main function
def main():
    parser = argparse.ArgumentParser(description="PatchManager Checks")
    parser.add_argument("-e", "--environment", required=True, help="Specify the environment (prod or non-prod)")
    parser.add_argument("-a", "--aws-account", required=True, help="Specify the AWS account ID example awsnamecompany awsnamecompany")
    args = parser.parse_args()

    env = args.environment
    aws_account = args.aws_account

    if env == "non-prod" and not aws_account.endswith("np"):
        aws_account += "np"

    check_commands(["aws", "jq", "sed", "awk", "grep"])

    global column_positions, csv_data
    column_positions = {}
    csv_data = {}

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

    ec2 = boto3.client('ec2')
    for ec2region in ['us-east-1', 'us-west-2', 'us-west-1']:
        instances = ec2.describe_instances(Filters=[{'Name': 'instance-state-name', 'Values': ['running', 'stopped']}], RegionName=ec2region)
        
        for reservation in instances['Reservations']:
            for instance in reservation['Instances']:
                instance_id = instance['InstanceId']
                instance_name = next((tag['Value'] for tag in instance['Tags'] if tag['Key'] == 'Name'), 'N/A')
                instance_state = instance['State']['Name']
                print(f"\n\nNow working: {instance_id} {ec2region}")

                if instance_state == "running":
                    print(f"\tThis {instance_name} ({instance_id}) is in >> {instance_state} Status <<")
                    print(f"\tLaunch Time: {instance['LaunchTime']}, Instance Type: {instance['InstanceType']}")
                    add_to_csv(row, "InstanceID", instance_id)
                    add_to_csv(row, 'Instance Name', instance_name)
                    add_to_csv(row, 'Instance State', "Running")
                    add_to_csv(row, "Region", ec2region)
                    check_patch_status(instance_id, ec2region, row)
                    chkalltags(instance_id, ec2region, row, env)
                    check_instance_ami(instance_id, ec2region, row)
                    row += 1
                elif instance_state == "stopped":
                    print(f"\tThis {instance_name} ({instance_id}) is in >> {instance_state} Status <<")
                    print(f"\tLaunch Time: {instance['LaunchTime']}, Instance Type: {instance['InstanceType']}")
                    add_to_csv(row, "InstanceID", instance_id)
                    add_to_csv(row, 'Instance Name', instance_name)
                    add_to_csv(row, "Instance State", "Stopped")
                    add_to_csv(row, "Region", ec2region)
                    row += 1
                else:
                    print(f"\tThis {instance_name} ({instance_id}) is in >> {instance_state} Status << No Checks further and will NOT be on Report.\n")
                    print(f"\tLaunch Time: {instance['LaunchTime']}, Instance Type: {instance['InstanceType']}")

    print("Now Generating CSV .. ")
    generate_csv(aws_account)

if __name__ == "__main__":
    main()

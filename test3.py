import os
import subprocess
import json
import datetime
from collections import defaultdict
import argparse
import shutil
import re

def check_commands(commands):
    """
    Check if the necessary commands are installed.
    """
    for cmd in commands:
        if not shutil.which(cmd):
            print(f"ERROR: {cmd} is required but it's not installed. Aborting.\n")
            exit(1)

def agedifference(start, end):
    """
    Calculate the difference in days between two date strings in the format YYYY-MM-DDTHH:MM:SS.
    """
    try:
        start_date = datetime.datetime.strptime(start.split('.')[0], "%Y-%m-%dT%H:%M:%S")
        end_date = datetime.datetime.strptime(end.split('.')[0], "%Y-%m-%dT%H:%M:%S")
        return (start_date - end_date).days
    except ValueError as e:
        print(f"Date Error: {e}")
        return None

def is_session_alive():
    """
    Check if the AWS session is still valid by verifying required environment variables and session information.
    """
    required_vars = ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"]
    for var in required_vars:
        if var not in os.environ:
            return False

    try:
        session_info = subprocess.getoutput("alks session ls 2>/dev/null | grep -v '─' | tr -d '│' | egrep 'ACCOUNT|IAM' | sed -r 's/\\x1B\\[[0-9;]*[a-zA-Z]//g'")
        if not session_info:
            return False

        session_lines = session_info.split('\n')
        access_key = session_lines[0].split()[0].replace('*', '')
        secret_key = session_lines[0].split()[1].replace('*', '').replace('…', '')

        if os.environ["AWS_ACCESS_KEY_ID"].endswith(access_key) and os.environ["AWS_SECRET_ACCESS_KEY"].endswith(secret_key):
            return True
    except Exception as e:
        print(f"Error checking session: {e}")
        return False

    return False

def open_alks_session(account):
    """
    Open an ALKS session for the specified account.
    """
    try:
        session_output = subprocess.getoutput(f"alks sessions open -a \"{account}\" -r \"Admin\" 2>/dev/null")
        if "export" in session_output:
            exec(session_output)  # Execute the session export commands in the current shell
            print("[ OK ]\n")
        else:
            print("[ Error ]\nFailed to open ALKS session.")
            print(session_output)
            exit(1)
    except Exception as e:
        print(f"Error opening ALKS session: {e}")
        exit(1)

def add_column(column_positions, csv_data, col_name, position=None):
    """
    Add or update column positions in the CSV data.
    """
    if position is None:
        position = len(column_positions) + 1
    for key in column_positions:
        if column_positions[key] >= position:
            column_positions[key] += 1
    column_positions[col_name] = position
    csv_data[f"1,{position}"] = col_name

def addtocsv(csv_data, column_positions, row, col_name, data):
    """
    Add data to the CSV, handling column headings if they are missing.
    """
    if col_name not in column_positions:
        add_column(column_positions, csv_data, col_name)
    col = column_positions[col_name]
    key = f"{row},{col}"
    if key in csv_data:
        csv_data[key] += f" {data}"
    else:
        csv_data[key] = data

def generatecsv(csv_data, column_positions, aws_account):
    """
    Generate a CSV file from the collected data.
    """
    dt = datetime.datetime.now().strftime("%d%B%Y_%H%M%S")
    filename = f"{aws_account}Report_{dt}.csv"
    try:
        with open(filename, "w") as file:
            max_row = max(int(k.split(',')[0]) for k in csv_data.keys())
            max_col = max(int(k.split(',')[1]) for k in csv_data.keys())
            for i in range(1, max_row + 1):
                line = ",".join(csv_data.get(f"{i},{j}", "") for j in range(1, max_col + 1))
                file.write(line.rstrip(',') + "\n")
        print(f"\t[ OK ]\n\n\t\tThe CSV file report is generated in  >>> {filename} <<<\n\n")
    except Exception as e:
        print(f"Error generating CSV: {e}")

def chkalltags(instance_id, region, row, env, csv_data, column_positions, TagstobeCheckedProd, TagstobeCheckedNONProd):
    """
    Check all required tags for an instance and add missing tags to the CSV.
    """
    tags_to_check = TagstobeCheckedProd if env == "prod" else TagstobeCheckedNONProd
    for tagcheck in tags_to_check:
        try:
            result = subprocess.getoutput(f"aws ec2 describe-tags --filters Name=resource-type,Values=instance Name=resource-id,Values={instance_id} --region {region} | jq -r \".Tags[] | select(.Key=='{tagcheck}') | .Value\"")
            if not result:
                print(f"\tError: Tag missing {tagcheck}")
                addtocsv(csv_data, column_positions, row, 'Tags missing', f"Missing: {tagcheck}")
        except Exception as e:
            print(f"Error checking tag {tagcheck}: {e}")

def checkspecialtag(instance_id, region, tagcheck):
    """
    Check if a specific tag is present for an instance.
    """
    try:
        result = subprocess.getoutput(f"aws ec2 describe-tags --filters Name=resource-type,Values=instance Name=resource-id,Values={instance_id} --region {region} | jq -r \".Tags[] | select(.Key=='{tagcheck}') | .Value\"")
        return bool(result)
    except Exception as e:
        print(f"Error checking special tag {tagcheck}: {e}")
        return False

def checkPatchStatus(instance_id, region, row, csv_data, column_positions):
    """
    Check the patch status of an instance and update the CSV with the findings.
    """
    print("Checking on Patches:")
    ok = 0

    try:
        ssmdata = subprocess.getoutput(f"aws ssm describe-instance-patch-states --instance-ids {instance_id} --region {region}")
        ssmdata_json = json.loads(ssmdata)
        installed_pending_reboot = ssmdata_json["InstancePatchStates"][0]["InstalledPendingRebootCount"]
        missing_count = ssmdata_json["InstancePatchStates"][0]["MissingCount"]

        if installed_pending_reboot == 0:
            ok += 1
        else:
            print("\tError: InstalledPendingRebootCount issue Non-Compliant: This instance needs to rebooted for the patches to be applied.")
            if checkspecialtag(instance_id, region, "company-ssm-managed-patch-install-reboot"):
                addtocsv(csv_data, column_positions, row, 'Tags missing', "company-ssm-managed-patch-install-reboot")
                print("\tInfo: Tag company-ssm-managed-patch-install-reboot is true. Seems like PatchManager needs to recheck in next run. Ignore this instance for now.")
            else:
                addtocsv(csv_data, column_positions, row, 'Tags missing', "company-ssm-managed-patch-install-reboot.")
                print("\tError: Required TAG missing: company-ssm-managed-patch-install-reboot.")

        if missing_count == 0:
            ok += 1

        if ok > 1:
            addtocsv(csv_data, column_positions, row, 'Patch required action', "Patches are applied")
            addtocsv(csv_data, column_positions, row, 'Patch Status', "Compliant")
            print("\t All patches applied and instance is Compliant [ OK ]")
        else:
            print("\tError: MissingCount. Non-Compliant: Patches are not applied, This instance need urgent attention.")
            addtocsv(csv_data, column_positions, row, 'Patch required action', "Patches are required to be applied")
            addtocsv(csv_data, column_positions, row, 'Patch Status', "Non-Compliant")
    except Exception as e:
        print(f"Error checking patch status: {e}")

def check_instance_ami(instance_details, instance_id, region, row, csv_data, column_positions):
    """
    Check the AMI details of an instance and suggest updates if needed.
    """
    print(f"Current AMI ID of the instance: {instance_id}")

    try:
        ami_id = next((i["ImageId"] for r in instance_details["Reservations"] for i in r["Instances"] if i["InstanceId"] == instance_id), None)
        ami_info = json.loads(subprocess.getoutput(f"aws ec2 describe-images --image-ids {ami_id} --region {region} --query 'Images[0]' --output json"))
        ami_name = ami_info["Name"]
        is_public = ami_info["Public"]
        creation_date = ami_info["CreationDate"]

        addtocsv(csv_data, column_positions, row, "Current AMI-name", ami_name)
        addtocsv(csv_data, column_positions, row, "Current AMI-ID", ami_id)
        addtocsv(csv_data, column_positions, row, "AMI_Visibility", "Public" if is_public else "Private")

        asg_info = json.loads(subprocess.getoutput(f"aws autoscaling describe-auto-scaling-instances --instance-ids {instance_id} --region {region} --query 'AutoScalingInstances[0]' --output json"))
        asg_name = asg_info.get("AutoScalingGroupName", "Not in ASG")
        addtocsv(csv_data, column_positions, row, "ASG Name", asg_name)

        if not is_public:
            print("\tThe AMI is private. No further checks.")
            return

        ami_name_pattern = re.sub(r'[0-9]{8}', '*', ami_name)
        latest_ami_info = json.loads(subprocess.getoutput(f"aws ec2 describe-images --region {region} --owners amazon --filters 'Name=name,Values={ami_name_pattern}' --query 'Images | sort_by(@, &CreationDate) | [-1]' --output json"))

        if not latest_ami_info:
            print("\tError: Unable to get the latest AMI information.")
            addtocsv(csv_data, column_positions, row, "AMI update suggestion", "Error: Unable to get the latest AMI information.")
            return

        latest_ami_name = latest_ami_info["Name"]
        latest_ami_id = latest_ami_info["ImageId"]
        latest_ami_date = latest_ami_info["CreationDate"]

        addtocsv(csv_data, column_positions, row, "Latest AMI-ID", latest_ami_id)
        addtocsv(csv_data, column_positions, row, "Latest AMI creation date", latest_ami_date)

        if creation_date == latest_ami_date:
            addtocsv(csv_data, column_positions, row, "AMI update suggestion", "Already at Latest")
            addtocsv(csv_data, column_positions, row, "AMI age", "No Difference")
        else:
            addtocsv(csv_data, column_positions, row, "AMI update suggestion", latest_ami_name)
            age_diff = agedifference(latest_ami_date, creation_date)
            addtocsv(csv_data, column_positions, row, "AMI age", f"{age_diff} days")
    except Exception as e:
        print(f"Error checking AMI details: {e}")

def main():
    parser = argparse.ArgumentParser(description="PatchManager Checks")
    parser.add_argument("-e", "--environment", required=True, help="Specify the environment (prod or non-prod)")
    parser.add_argument("-a", "--aws-account", required=True, help="Specify the AWS account ID example awsacs awsnamecompany")
    args = parser.parse_args()

    ENV = args.environment
    AWS_ACCOUNT = args.aws_account

    if ENV == "non-prod" and not AWS_ACCOUNT.endswith("np"):
        AWS_ACCOUNT += "np"

    # Step 1: Check if essential commands are installed
    check_commands(["aws", "jq", "alks", "sed", "awk", "grep"])
    print("Checking if essential commands are installed:\t[ OK ]\n")

    # Step 2: Check AWS session and get session if needed
    account = subprocess.getoutput(f"alks developer accounts 2>/dev/null | grep {AWS_ACCOUNT} | grep ALKSAdmin | awk '{{ printf(\"%s %s %s\",$2,$3,$4) }}'")
    print(f"Checking AWS session for {account} and Admin")

    if not is_session_alive():
        print("[ Error ] \nAWS session has expired. Now trying to get sessions.")
        open_alks_session(account)
        if not is_session_alive():
            print(f"[ Error ]\nPossibly you do not have access to {AWS_ACCOUNT} as Admin. Admin access is needed to perform Patch checking.")
            exit(1)
    print("[ OK ]\n")

    # Step 3: Initialize column positions and CSV data
    column_positions = {}
    csv_data = defaultdict(str)

    add_column(column_positions, csv_data, 'InstanceID', 1)
    add_column(column_positions, csv_data, 'Instance Name', 2)
    add_column(column_positions, csv_data, 'Instance State', 3)
    add_column(column_positions, csv_data, 'Region', 4)
    add_column(column_positions, csv_data, 'Patch Status', 5)
    add_column(column_positions, csv_data, 'Patch required action', 6)
    add_column(column_positions, csv_data, 'Tags missing', 7)
    add_column(column_positions, csv_data, 'Current AMI-name', 8)
    add_column(column_positions, csv_data, 'Current AMI-ID', 9)
    add_column(column_positions, csv_data, 'AMI_Visibility', 10)
    add_column(column_positions, csv_data, 'AMI update suggestion', 11)
    add_column(column_positions, csv_data, 'Latest AMI-ID', 12)
    add_column(column_positions, csv_data, 'Latest AMI creation date', 13)
    add_column(column_positions, csv_data, 'AMI age', 14)
    add_column(column_positions, csv_data, 'ASG Name', 15)
    add_column(column_positions, csv_data, 'Notes', 16)

    row = 2

    # Step 4: Process instances in specified regions
    regions = ["us-east-1", "us-west-2", "us-west-1"]
    for region in regions:
        try:
            instance_details = json.loads(subprocess.getoutput(f"aws ec2 describe-instances --region {region}"))
            for reservation in instance_details["Reservations"]:
                for instance in reservation["Instances"]:
                    instance_id = instance["InstanceId"]
                    instance_name = next((tag["Value"] for tag in instance["Tags"] if tag["Key"] == "Name"), "N/A")
                    state = instance["State"]["Name"]
                    print(f"\n\nNow working: {instance_id} {region}")
                    print(f"\tThis {instance_name} ({instance_id}) is in >> {state} Status <<:")

                    if state == "running":
                        addtocsv(csv_data, column_positions, row, "InstanceID", instance_id)
                        addtocsv(csv_data, column_positions, row, 'Instance Name', instance_name)
                        addtocsv(csv_data, column_positions, row, 'Instance State', "Running")
                        addtocsv(csv_data, column_positions, row, "Region", region)
                        checkPatchStatus(instance_id, region, row, csv_data, column_positions)
                        chkalltags(instance_id, region, row, ENV, csv_data, column_positions, 
                                   ["company-ssm-managed-patch-install-no-reboot"], 
                                   ["company-ssm-managed-patch-install-reboot", "company:ssm:managed-qualys-install-linux", "company:ssm:managed-crowdstrike-install", "company-ssm-managed-scan"])
                        check_instance_ami(instance_details, instance_id, region, row, csv_data, column_positions)
                        row += 1
                    elif state == "stopped":
                        addtocsv(csv_data, column_positions, row, "InstanceID", instance_id)
                        addtocsv(csv_data, column_positions, row, 'Instance Name', instance_name)
                        addtocsv(csv_data, column_positions, row, "Instance State", "Stopped")
                        addtocsv(csv_data, column_positions, row, "Region", region)
                        row += 1
                    else:
                        print(f"\tThis {instance_name} ({instance_id}) is in >> {state} Status << No Checks further and will NOT be on Report.\n")
        except Exception as e:
            print(f"Error processing region {region}: {e}")

    # Step 5: Generate CSV report
    print("Now Generating CSV .. ")
    generatecsv(csv_data, column_positions, AWS_ACCOUNT)

if __name__ == "__main__":
    main()

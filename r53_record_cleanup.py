import argparse
import logging, logging.handlers
import os
import tempfile
import yaml
import boto3, botocore
import datetime

logging.getLogger("botocore").setLevel(logging.CRITICAL)

KEEP_LIST = []


def expand_keep_list(zone_name):
    if not zone_name.endswith('.'):
        zone_name += '.'
    KEEP_LIST[:] = [x + '.' + zone_name for x in KEEP_LIST]


def get_hosted_zone_list(profile=None):
    session = boto3.session.Session(profile_name=profile)
    r53_client = session.client('route53')
    result = None
    try:
        query = r53_client.list_hosted_zones()
        result = query['HostedZones']
    except botocore.exceptions.ClientError as e:
        logging.error('Unexpected error: %s' % e)
    return result


def get_hosted_zone_by_name(zone_name, profile=None):
    session = boto3.session.Session(profile_name=profile)
    r53_client = session.client('route53')
    result = None
    if not zone_name.endswith('.'):
        zone_name += '.'
    zone_list = get_hosted_zone_list(profile=profile)
    if zone_list:
        for zone in zone_list:
            if zone_name == zone['Name']:
                try:
                    query = r53_client.get_hosted_zone(Id=zone['Id'])
                    result = query['HostedZone']
                    break
                except botocore.exceptions.ClientError as e:
                    if e.response['Error']['Code'] == 'NoSuchHostedZone':
                        logging.error("Zone does not exist")
                    else:
                        logging.error('Unexpected error: %s' % e)
    return result


def get_all_records_in_zone(zone_id, profile=None):
    session = boto3.session.Session(profile_name=profile)
    r53_client = session.client('route53')
    resource_record_sets = []
    try:
        current_set = r53_client.list_resource_record_sets(HostedZoneId=zone_id)
        resource_record_sets.extend(current_set['ResourceRecordSets'])
        isTruncated = current_set['IsTruncated']
        while isTruncated:
            start_name = current_set['NextRecordName']
            current_set = r53_client.list_resource_record_sets(HostedZoneId=zone_id, StartRecordName=start_name)
            resource_record_sets.extend(current_set['ResourceRecordSets'])
            isTruncated = current_set['IsTruncated']
    except botocore.exceptions.ClientError as e:
        logging.error('Unexpected error: %s' % e)
    return resource_record_sets


def restore_deleted_records(file_path):
    session = boto3.session.Session()
    r53_client = session.client('route53')

    if not os.path.exists(file_path):
        logging.critical('Invalid file path provided')
        exit(1)
    else:
        records = []
        with open(file_path, 'r') as record_file:
            records = yaml.load(record_file, yaml.SafeLoader)

    logging.info('Restoring records...')

    # Loop through all records, creating change sets of 50 records at a time
    number_of_records = len(records)
    start_record = 0
    records_processed = 0
    batch_size = 100
    while records_processed < number_of_records:
        change_set = []
        # Get the next <batch_size> records - if they exist
        end_record = start_record + batch_size
        if end_record > number_of_records:
            end_record = number_of_records
        records_to_process = records[start_record:end_record:1]
        zone_id = records_to_process[0]['AliasTarget']['HostedZoneId']
        for record in records_to_process:
            resource_record_set = {
                'AliasTarget': {
                    'HostedZoneId': record['AliasTarget']['HostedZoneId'],
                    'EvaluateTargetHealth': record['AliasTarget']['EvaluateTargetHealth'],
                    'DNSName': record['AliasTarget']['DNSName']
                },
                'Type': record['Type'],
                'Name': record['Name']
            }
            change = {'Action': 'UPSERT', 'ResourceRecordSet': resource_record_set}
            change_set.append(change)
        change_batch = {'Comment' : 'Restoring resource records', 'Changes' : change_set}
        try:
            logging.debug("Attempting the following changes: %s" % change_batch )
            r53_client.change_resource_record_sets(HostedZoneId=zone_id, ChangeBatch=change_batch)
            logging.debug("Route53 Change Resource Record request received successfully")
        except botocore.exceptions.ClientError as e:
            logging.error("Received error:  %s" % (e))
            exit(1)
        records_processed += (end_record-start_record)
        start_record = end_record
    logging.info('Record restoration initiated - check AWS Console to make sure it completed.')



def delete_records(record_list):
    session = boto3.session.Session()
    r53_client = session.client('route53')

    # Loop through all records, creating change sets of 50 records at a time
    number_of_records = len(record_list)
    logging.debug('There are %d records to delete' % number_of_records)
    start_record = 0
    records_processed = 0
    batch_size = 100
    while records_processed < number_of_records:
        change_set = []
        # Get the next <batch_size> records - if they exist
        end_record = start_record + batch_size
        if end_record > number_of_records:
            end_record = number_of_records
        logging.debug('processing records %d to %d' % (start_record, end_record))
        records_to_process = record_list[start_record:end_record:1]
        logging.debug('%s' % records_to_process)
        zone_id = records_to_process[0]['AliasTarget']['HostedZoneId']
        for record in records_to_process:
            resource_record_set = {
                'AliasTarget': {
                    'HostedZoneId': record['AliasTarget']['HostedZoneId'],
                    'EvaluateTargetHealth': record['AliasTarget']['EvaluateTargetHealth'],
                    'DNSName': record['AliasTarget']['DNSName']
                },
                'Type': record['Type'],
                'Name': record['Name']
            }
            change = {'Action': 'DELETE', 'ResourceRecordSet': resource_record_set}
            change_set.append(change)
        change_batch = {'Comment' : 'Deleting resource records', 'Changes' : change_set}
        try:
            logging.debug("Attempting the following changes: %s" % change_batch )
            r53_client.change_resource_record_sets(HostedZoneId=zone_id, ChangeBatch=change_batch)
            logging.debug("Route53 Change Resource Record request received successfully")
        except botocore.exceptions.ClientError as e:
            logging.error("Connection error to AWS. Check your credentials")
            logging.error("Received error:  %s" % (e))
            exit(1)
        records_processed += (end_record-start_record)
        start_record = end_record


def r53_cleanup(zone_name, target_alias, dryrun=False):
    zone = get_hosted_zone_by_name(zone_name)
    record_set = get_all_records_in_zone(zone['Id'])
    logging.debug(record_set)

    if not target_alias.endswith('.'):
        target_alias += '.'

    to_delete=[]
    for record in record_set:
        record_name = record['Name']
        record_type = record['Type']
        if record_type == 'A':
            if record_name == zone['Name']:
                logging.debug('Skipping %s because it is the zone being searched' % record_name)
                continue
            if record_name not in KEEP_LIST:
                if 'AliasTarget' in record:
                    dns_name = record['AliasTarget']['DNSName']
                    if dns_name == target_alias:
                        logging.debug(' To Be Deleted: %s' % record['Name'])
                        to_delete.append(record)
                    else:
                        logging.debug("Skipping %s because Alias Target doesn't match" % record_name)
                else:
                    logging.debug("Skipping %s because it does't have an Alias Target" % record_name)
            else:
                logging.debug('Skipping %s because it is in the KEEP_LIST' % record_name)
        else:
            logging.debug('Skipping %s due to incorrect record type (%s)' % (record_name, record_type))

    temp_file = tempfile.NamedTemporaryFile(delete=False)
    with temp_file as output_file:
        yaml.safe_dump(to_delete, output_file)
    temp_file_yaml = temp_file.name + '.yaml'
    os.rename(temp_file.name, temp_file_yaml)
    logging.info('Records to be deleted written to "%s"' % temp_file_yaml)

    deleted_record_count = len(to_delete)
    # Now actually delete them
    logging.info("Found %d records to be deleted" % deleted_record_count)
    if not dryrun:
        logging.info('Deleting records...')
        logging.info(str(datetime.datetime.now()))
        delete_records(to_delete)
        logging.info(str(datetime.datetime.now()))
        logging.info('Record deletion complete (or pending) - check AWS Console to make sure things are as expected.')
        logging.info('To restore these records, use --restore %s' % temp_file_yaml)
    else:
        logging.info('dryrun selected - no records deleted')


if __name__ == "__main__":

    LOG_FILENAME = 'r53-record-cleanup.log'

    description = "Cleanup old R53 Records\n"
    description += "Note: The following environment variables can be set prior to execution\n"
    description += "      of the script (or alternatively, set them using script parameters)\n\n"
    description += "      AWS_ACCESS_KEY_ID\n"
    description += "      AWS_SECRET_ACCESS_KEY"

    parser = argparse.ArgumentParser(description=description, formatter_class=argparse.RawTextHelpFormatter)

    parser.add_argument("--aws-access-key-id", help="AWS Access Key ID", dest='aws_access_key', required=False)
    parser.add_argument("--aws-secret-access-key", help="AWS Secret Access Key", dest='aws_secret_key', required=False)
    parser.add_argument("--hosted-zone", help="Hosted Zone Name", dest='zone_name', required=False)
    parser.add_argument("--target-alias", help="Target Alias", dest='target_alias', required=False)
    parser.add_argument("--keep-list", help="Add to the keep list", dest='keep_list', nargs='+', required=False)
    parser.add_argument("--restore", help="Restore deleted records", dest='restore_file', required=False)
    parser.add_argument("--verbose", help="Turn on DEBUG logging", action='store_true', required=False)
    parser.add_argument("--dryrun", help="Do a dryrun - no changes will be performed", dest='dryrun',
                        action='store_true', default=False,
                        required=False)
    args = parser.parse_args()

    log_level = logging.INFO

    if args.verbose:
        print('Verbose logging selected')
        log_level = logging.DEBUG

    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    # create file handler which logs even debug messages
    fh = logging.handlers.RotatingFileHandler(LOG_FILENAME, maxBytes=5242880, backupCount=5)
    fh.setLevel(logging.DEBUG)
    # create console handler using level set in log_level
    ch = logging.StreamHandler()
    ch.setLevel(log_level)
    console_formatter = logging.Formatter('%(levelname)8s: %(message)s')
    ch.setFormatter(console_formatter)
    file_formatter = logging.Formatter('%(asctime)s - %(levelname)8s: %(message)s')
    fh.setFormatter(file_formatter)
    # Add the handlers to the logger
    logger.addHandler(fh)
    logger.addHandler(ch)

    if not os.environ.get('AWS_ACCESS_KEY_ID'):
        if not args.aws_access_key:
            logging.critical('AWS Access Key Id not set - cannot continue')
            logging.critical('Please set the AWS_ACCESS_KEY_ID environment variable or pass in using --aws-access-key')
            exit(1)
        else:
            os.environ['AWS_ACCESS_KEY_ID'] = args.aws_access_key

    if not os.environ.get('AWS_SECRET_ACCESS_KEY'):
        if not args.aws_secret_key:
            logging.critical('AWS Secret Access Key not set - cannot continue')
            logging.critical('Please set the AWS_SECRET_ACCESS_KEY environment variable or pass in using --aws-secret-key')
            exit(1)
        else:
            os.environ['AWS_SECRET_ACCESS_KEY'] = args.aws_secret_key

    logging.debug('INIT')

    if args.restore_file:
        restore_deleted_records(args.restore_file)
    else:
        if not args.zone_name:
            logging.critical('Must provide a zone_name to search')
            exit(1)

        if not args.target_alias:
            logging.critical('Must provide a target_alias')
            exit(1)

        logging.info('Cleaning up Route 53 records in Hosted Zone %s with a target alias of %s' % (args.zone_name, args.target_alias))

        if args.keep_list:
            logging.info("Adding the following to the keep list: %s" % args.keep_list)
            for item in args.keep_list:
                KEEP_LIST.append(item.replace('*', "\\052"))

        if len(KEEP_LIST) > 0:
            expand_keep_list(args.zone_name)

        logging.info("Records matching the following keep list will NOT be removed:")
        for item in KEEP_LIST:
            logging.info("   %s" % item)

        r53_cleanup(args.zone_name, args.target_alias, args.dryrun)
    logging.info('COMPLETE')

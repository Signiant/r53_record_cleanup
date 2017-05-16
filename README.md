# r53_record_cleanup
Clean up old Route 53 Records that match certain criteria

```
usage: r53_record_cleanup.py [-h] [--aws-access-key-id AWS_ACCESS_KEY]
                             [--aws-secret-access-key AWS_SECRET_KEY]
                             [--hosted-zone ZONE_NAME]
                             [--target-alias TARGET_ALIAS]
                             [--keep-list KEEP_LIST [KEEP_LIST ...]]
                             [--restore RESTORE_FILE] [--verbose] [--dryrun]

Cleanup old R53 Records
Note: The following environment variables can be set prior to execution
      of the script (or alternatively, set them using script parameters)

      AWS_ACCESS_KEY_ID
      AWS_SECRET_ACCESS_KEY

optional arguments:
  -h, --help            show this help message and exit
  --aws-access-key-id AWS_ACCESS_KEY
                        AWS Access Key ID
  --aws-secret-access-key AWS_SECRET_KEY
                        AWS Secret Access Key
  --hosted-zone ZONE_NAME
                        Hosted Zone Name
  --target-alias TARGET_ALIAS
                        Target Alias
  --keep-list KEEP_LIST [KEEP_LIST ...]
                        Add to the keep list
  --restore RESTORE_FILE
                        Restore deleted records
  --verbose             Turn on DEBUG logging
  --dryrun              Do a dryrun - no changes will be performed

```

Example:

```
python r53_record_cleanup.py --hosted-zone example.com --target-alias prod.example.com --keep-list manage '*'
```
#!/usr/bin/python
'''
Starts an incremental backup using duplicity, with periodic backups over time.
This is meant to be a personal script and so the coding standards might be a
little bit lacking, since there's nobody to code review.
'''
# The basic process for this backup is this:
# - Do a zfs snapshot. This will ensure that the FS does not change throughout
#   the backup process
# - Run a duplicity snapshot on the backup. This should be full if beyond a
#   certain timeframe (2 weeks?). That way if something gets hosed, the biggest
#   loss is over 2 weeks.
# - Optionally, run a verification on the old backups
# - Delete the old backups if older than 2 backup cycles. This is to save $$.
#   Think about this before implementing (If it runs away it could blow up
#   everything).
# - On each of these, have a sensible strategy on failure.
# - Mail me on failure of the job
# - Mail me on success of the job. Really I've got like 1TB of gmail space
#   these 1k mails do nothing.
# - Delete the zfs snapshot. This should not happen if any steps fail.

import argparse
import datetime
import subprocess
import logging
import os
import sys

CONFIG = {'s3url': None, 'root': None, 'filesystem': None}
CONFIG_FILE = '/etc/local/backups.conf'
FORMAT = '%(asctime)-15s : %(levelname)-10s - %(msg)'
DEBUG = False
logging.basicConfig(format=FORMAT)
LOG = logging.getLogger('root')
ENDPOINT = 'https://storage.googleapis.com'

def _exec(*args):
    '''
    executes the given command, and pipes all of the output to the standard
    logger
    '''
    print(' '.join(args))
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    line = proc.stdout.readline()
    while line:
        print('  ' + line.decode('utf8').strip())
        line = proc.stdout.readline()
    if proc.wait() != 0:
        raise IOError("Process crashed. Might want to take a look at that.")

def timestamp():
    ''' Returns the timestamp in seconds '''
    # you can write java in any language.
    return int((datetime.datetime.now(datetime.UTC) - datetime.datetime(1970, 1, 1, tzinfo=datetime.UTC))
               .total_seconds())

class Duplicity(object):
    def __init__(self, url, dryrun, path, ekey_id, skey_id, cachefile, binary):
        self.binary = binary
        self.url = url
        self.dryrun = dryrun
        self.path = path
        self.enc_key = ekey_id
        self.sign_key = skey_id
        self.cachefile = cachefile

    def verify(self):
        ''' calls duplicity verify on the thing '''
        pass

    def recover(self):
        '''Calls duplicity recover'''
        cmd = [self.binary,
               'restore',
               '--use-agent',
               '--archive-dir', self.cachefile,
               '--encrypt-key', self.enc_key,
               '--sign-key', self.sign_key,
               '--s3-endpoint-url', ENDPOINT]
        if self.dryrun:
            cmd += ['--dry-run']
        cmd += [self.url, self.path]
        _exec(*cmd)

    def backup(self):
        '''Calls duplicity backup'''
        cmd = [self.binary, 'backup',
               '--use-agent',
               '--archive-dir', self.cachefile,
               '--full-if-older-than', time_format(weeks=14),
               '--exclude', '**/nobackups',
               '--exclude-if-present', '.nobackups',
               '--encrypt-key', self.enc_key,
               '--sign-key', self.sign_key,
               '--s3-endpoint-url', ENDPOINT,
               '--allow-source-mismatch']
        if self.dryrun:
            cmd += ['--dry-run']
        cmd += [self.path, self.url]
        _exec(*cmd)

    def prune(self):
        '''Calls duplicity to prune old backups and incremental backups'''
        cmd = [self.binary,
               '--archive-dir', self.cachefile,
               'remove-all-but-n-full', str(4),
               '--s3-endpoint-url', ENDPOINT,
               '--force']
        cmd += [self.url]
        _exec(*cmd)
        cmd = [self.binary,
               '--archive-dir', self.cachefile,
               'remove-all-inc-of-but-n-full', str(2),
               '--s3-endpoint-url', ENDPOINT,
               '--force']
        cmd += [self.url]
        _exec(*cmd)

    def cleanup(self):
        '''Calls duplicity to prune old backups and incremental backups'''
        cmd = [self.binary, 'cleanup',
               '--archive-dir', self.cachefile,
               '--encrypt-key', self.enc_key,
               '--sign-key', self.sign_key,
               '--s3-endpoint-url', ENDPOINT,
               '--force']
        cmd += [self.url]
        _exec(*cmd)

class Snapshot(object):
    '''
    Represents a zfs snapshot. when _enter_ is called, it takes a snapshot of
    the zfs directory and maintains that file path until __exit__
    '''

    def __init__(self, filesystem, root, create_snapshot):
        super(Snapshot, self).__init__()
        self.filesystem = filesystem
        self.timestamp = timestamp()
        self.name = '%s@%s' % (self.filesystem, 'duplicity')
        self.root = root
        self.create_snapshot = create_snapshot

    def exists(self):
        ''' Returns true if the snapshot path exists '''
        return os.path.exists(os.path.join(self.root, '.zfs', 'snapshot', 'duplicity'))

    def __enter__(self):
        ''' Takes a temporary ZFS snapshot, s I don't have to worry about it.'''
        if self.create_snapshot:
            _exec('zfs', 'snapshot', self.name)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        '''
        Removes the ZFS snapshot, so that I don't have to worry about it later.
        '''
        if self.create_snapshot:
            _exec('zfs', 'destroy', self.name)

    def rebase(self, root, path):
        ''' Rewrite the path from the zfs root to the zfs snapshot '''
        return os.path.join(root, '.zfs', 'snapshot', 'duplicity', path)

def time_format(years=0, months=0, weeks=0, days=0, hours=0, minutes=0, seconds=0):
    '''Returns a relative time format as specified in the duplicity'''
    symbols = ((years, 'Y'), (months, 'M'), (weeks, 'W'), (days, 'D'),
               (hours, 'h'), (minutes, 'm'), (seconds, 's'))
    fmt = []
    for symbol in symbols:
        if symbol[0] > 0:
            fmt.extend((str(x) for x in symbol))
    return ''.join(fmt)

def parse_arguments(config):
    ''' Parses arguments for the application '''
    parser = argparse.ArgumentParser(description='Run by backups, hourly')
    # print config
    parser.add_argument('--filesystem', type=str,
                        default=config['filesystem'].strip(),
                        help="ZFS filesystem to take a snapshot of")
    parser.add_argument('--root', type=str, help="Path to back up",
                        default=config['root'].strip())
    parser.add_argument('--path', type=str, help="Path to restore to",
                        default=config['restore_path'].strip())
    parser.add_argument('--s3url', type=str, help="S3 URL to upload to",
                        default=config['s3url'].strip())
    parser.add_argument('-c', '--config', type=str, help="Configuration file")
    parser.add_argument('-d', '--dryrun', type=str, help="Dry run")
    parser.add_argument('-e', '--encryption_key_id', type=str, help="Do stuff",
                        default=config['encrypt_key_id'].strip())
    parser.add_argument('-s', '--signing_key_id', type=str, help="Do stuff",
                        default=config['sign_key_id'].strip())
    parser.add_argument('-m', '--command', help="Command to run to back up",
                        default='backup',
                        choices=['backup', 'recover', 'cleanup'])
    parser.add_argument('--cache', type=str, help="Path to cache folder",
                        default=config['cachefile'].strip())
    parser.add_argument('--create-snapshot', action='store_true', dest='create_snapshot',
                        help="Create the snapshot before backing up.")
    parser.add_argument('--nocreate-snapshot', action='store_false', dest='create_snapshot',
                        help="Don't Create the snapshot before backing up.")
    parser.set_defaults(create_snapshot=True)
    return parser.parse_args()

def backup(opts, config):
    ''' Perform a backup of the current zfs snapshot '''
    snap = Snapshot(opts.filesystem, opts.root, opts.create_snapshot)
    if snap.exists():
        if opts.create_snapshot:
            print("Warning: snapshot %s directory already exists." % opts.root)
        else:
            print("Snapshot %s already exists. continuing." % opts.root)
    with snap:
        duplicity = Duplicity(config['s3url'], DEBUG,
                              snap.rebase(opts.root, ''),
                              opts.encryption_key_id,
                              opts.signing_key_id,
                              opts.cache,
                              binary=config['binary'])
        duplicity.backup()
        duplicity.prune()

def recover(opts, config):
    ''' Perform a recovery from the backup to the current directory '''
    duplicity = Duplicity(config['s3url'], DEBUG,
                          opts.path,
                          opts.encryption_key_id,
                          opts.signing_key_id,
                          opts.cache,
                          binary=config['binary'])
    duplicity.recover()

def cleanup(opts, config):
    ''' Performs a full cleanup of the backup signature files '''
    duplicity = Duplicity(config['s3url'], DEBUG,
                          opts.path,
                          opts.encryption_key_id,
                          opts.signing_key_id,
                          opts.cache,
                          binary=config['binary'])
    duplicity.cleanup()

def main():
    if os.geteuid() != 0:
        sys.stderr.write("Requires a uid of r00t\n")
        sys.exit(1)
    config = {}

    exec(open(CONFIG_FILE).read(), config)
    args = parse_arguments(config)
    os.environ['AWS_ACCESS_KEY_ID'] = config['access_key']
    os.environ['AWS_SECRET_ACCESS_KEY'] = config['secret_access_key']
    if args.command == 'recover':
        recover(args, config)
    elif args.command == 'cleanup':
        cleanup(args, config)
    else:
        backup(args, config)

if __name__ == '__main__':
    main()


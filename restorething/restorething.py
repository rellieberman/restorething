#!/usr/bin/env python
# -*- coding: utf-8 -*-

import io
import os
import re
import sys
import time

import rtlog
import rttools
import dbindex
import dbrestore

import logging
import logging.config
import logging.handlers
import ConfigParser

import argparse                                # import cli argument
from argparse import RawTextHelpFormatter      # Formatting help


def process_cli(working_dir, version):
    # processes cli arguments and usage guide
    parser = argparse.ArgumentParser(prog='restorething',
                    description='''Restore tool for syncthing versioning archive''',
                    epilog='''Command line examples \n\n \
                    POSIX Users \n \
                    python -m restorething 20160815 -hr 6 -vd sync/.stversions \n \
                    python -m restorething 20160815 -hr 6 -pm 10 -vd sync/.stversions -ns -rd test \n \
                     \n \
                    Windows Users \n \
                    python -m restorething 20160815 -hr 6 -vd sync\\.stversions \n \
                    python -m restorething 20160815 -hr 6 -pm 10 -vd sync\\.stversions -ns -rd test''',
                    formatter_class=RawTextHelpFormatter)
    g1 = parser.add_mutually_exclusive_group()
    g2 = parser.add_mutually_exclusive_group()
    parser.add_argument('date',
                        type=int,
                        metavar=('{date in format YYYYMMDD}'),
                        help='Date to restore files, date will be used to find closest file before or after date')
    parser.add_argument('-hr', '--hour',
                        default='12',
                        type=int,
                        choices=range(0, 24),
                        metavar=('{0..24}'),
                        help='Hour to restore files, time will be used to find closest file before or after time - Default = 12, 0 = 12am, 12 = 12pm, 17 = 5pm')
    g1.add_argument('-b', '--before',
                        action="store_true",
                        help='Restore files before desired date/time only - Default = disabled')
    g1.add_argument('-a', '--after',
                        action="store_true",
                        help='Restore files after desired date/time only - Default = disabled')
    g1.add_argument('-pm', '--plus-minus',
                        default='0',
                        type=int,
                        metavar=('{int}'),
                        help='Limit restore date/time plus/minus hours for desired date/time default = 0, 0 = disabled, 2 = +/- 2 hour')
    g1.add_argument('-ai','--all-instances',
                        default=None,
                        type=str,
                        metavar=('{absolute path of file}'),
                        help='Filter specific DIR and filename and restore all instances, default = Disabled')
    parser.add_argument('-vd', '--versions-dir',
                        default='.stversions',
                        type=str,
                        metavar=('{dir}'),
                        help='Versioning directory to index, default = .stversions')
    parser.add_argument('-rd', '--restore-dir',
                        default='restore',
                        type=str,
                        metavar=('{dir path}'),
                        help='Restore DIR, default = restore')
    parser.add_argument('-dd', '--db-dir',
                        default=working_dir,
                        type=str,
                        metavar=('{dir path}'),
                        help='Directory to find DB file, default = %s' % working_dir)
    parser.add_argument('-df', '--db-file',
                        default='restorething.db',
                        type=str,
                        metavar=('{filename}'),
                        help='DB file name, default = restorething.db')
    parser.add_argument('-nf', '--no-freeze',
                        action="store_true",
                        help='No 24hr DB freeze, default = disabled')
    parser.add_argument('-nd', '--no-delete',
                        action="store_true",
                        help='No deleted or renamed files in restore, default = disabled')
    parser.add_argument('-ic', '--inc-conflict',
                        action="store_true",
                        help='Inc conflict files in restore, default = disabled')
    parser.add_argument('-ns', '--no-sim',
                        action="store_true",
                        help='No simulate, restore for real, default = disabled')
    parser.add_argument('-f', '--force',
                        action="store_true",
                        help='Overwrite files without user confirmation, default = disabled')
    g2.add_argument('-ff', '--filter-file',
                        default=None,
                        type=str,
                        metavar=('{string}'),
                        help='Filter out specific filename, default = No filtering')
    g2.add_argument('-fd', '--filter-dir',
                        default=None,
                        type=str,
                        metavar=('{string}'),
                        help='Filter specific DIR, default = No filtering')
    g2.add_argument('-fb', '--filter-dirandfile',
                        default=None,
                        type=str,
                        metavar=('{absolute path of file}'),
                        help='Filter specific DIR and filename, default = No filtering')
    parser.add_argument('-d', '--debug',
                        action="store_true",
                        help='Enable debug output to console')
    parser.add_argument('--version',
                        action='version',
                        version='%(prog)s v'+version)

    args = parser.parse_args()
    return args


def validate_cli(args):
    logger = logging.getLogger(__name__)

    # validate date string
    try:
        d = rttools.validate_cli_date(args.date)
    except Exception, err:
        logger.error('Validating user input - %s' % str(err))
        sys.exit(1)

    # process time - was validated by argeparse
    h = rttools.process_cli_time(args.hour)

    # convert date and hour to epoch value
    try:
        cli_epoch = rttools.get_epoch(d, h)
    except Exception, err:
        logger.error('Validating user input - %s' % str(err))
        sys.exit(1)

    # check write permissions
    try:
        rttools.permissions(args)
    except Exception, err:
        logger.error(str(err))
        sys.exit(1)

    # test restore dir path for .stfolder or .stversions
    restdir_abs_path = rttools.convert_to_abspath(args.restore_dir, 'Restore DIR')
    st_op_dir = ['.stfolder', '.stversions']
    for stdir in st_op_dir:
        if rttools.restoredir_check(restdir_abs_path, stdir):
            if not rttools.warnuser('''\nRestoring files to syncthing dir, recommend restoring to dir above syncthing dir.\nConfirm if you want to proceed... y/n [y] '''):
                logger.debug('User acknowledged warning and chose to exit')
                sys.exit(1)
            else:
                logger.debug('User acknowledged warning and chose to continue')
                print '''Continuing...'''
                break
    # test filters that require absolute path
    if args.all_instances is not None:
        if not rttools.test_abs(args.all_instances):
            logger.error('File path is not absolute see user input -ai %s, exiting....', args.all_instances)
            sys.exit(1)
        else:
            logger.debug('Filter for all instances is absolute %s', args.all_instances)
    if args.filter_dirandfile is not None:
        if not rttools.test_abs(args.filter_dirandfile):
            logger.error('File path is not absolute see user input -fb %s, exiting....', args.filter_dirandfile)
            sys.exit(1)
        else:
            logger.debug('Filter for both DIR and file is absolute %s', args.filter_dirandfile)

    return cli_epoch, restdir_abs_path


def main():
    '''
    The main entry point of the application
    '''
    
    working_dir = rttools.process_working_dir()
    try:
        version=rttools.get_version('_version.py')
    except Exception, err:
        sys.stderr.write('ERROR: %s' % str(err))
        sys.exit(1)
    
    # process arguments from cli
    args = process_cli(working_dir, version)

    # load the logging configuration
    logging_file = rtlog.main(working_dir, args)
    try:
        logging.config.fileConfig(logging_file, disable_existing_loggers=False)
    except Exception, err:
        sys.stderr.write('ERROR: log config file - %s' % str(err))
        sys.exit(1)
    logger = logging.getLogger(__name__)

    logger.debug('CLI Arguments %s', args)

    # validate the cli
    cli_epoch, restdir_abs_path = validate_cli(args)

    # index and filter database
    database_file = os.path.join(working_dir, args.db_file)
    dbindex.main(database_file, args.no_freeze, args.versions_dir)
    dbrestore.main(database_file, cli_epoch, restdir_abs_path, args)


if __name__ == "__main__":
    main()

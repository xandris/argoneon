import logging
from sys import stdout

FORMAT_STRING = '%(asctime)s %(process)d [%(levelname)s] %(message)s'
DATE_FORMAT = '%b %d %y %H:%M:%S'


def enable(enableDebug: bool = False):
    logging.basicConfig(stream=stdout,
                        level=logging.DEBUG,
                        format=FORMAT_STRING,
                        datefmt=DATE_FORMAT)


def debug(message, *args): logging.debug(message, *args)


def info(message, *args): logging.info(message, *args)


def warning(message, *args): logging.warning(message, *args)


def error(message, *args): logging.error(message, *args)

from argparse import ArgumentParser, _SubParsersAction
from typing import Any, Callable, Dict, Protocol, TypedDict

from .version import ARGON_VERSION


class Args(Protocol):
    command: str
    func: Callable


class ArgDefinition(TypedDict):
    type: Any
    required: bool
    default: Any
    help: str


CliParameters = Dict[str, ArgDefinition]


class Cli(object):
    parser: ArgumentParser
    subParsers: _SubParsersAction

    def __init__(self, description: str = None):
        self.parser = ArgumentParser(description=description)
        self.parser.add_argument('-v', '--version', help='Print the version of the script.', action='store_true')
        self.subParsers = self.parser.add_subparsers(dest='command')

    def command(self, help: str | None = None, **args: ArgDefinition):
        def decorate(f):
            name: str = f.__name__
            sub: ArgumentParser = self.subParsers.add_parser(name.removeprefix('cmd_'), help=help, description=help)
            sub.set_defaults(func=f)
            for k, v in args.items():
                sub.add_argument(k, **v)
            return f
        return decorate

    def __call__(self):
        args = self.parser.parse_args()
        if args.version:
            print(ARGON_VERSION)
            exit(0)

        if not 'func' in args:
            self.parser.print_help()
            exit(1)

        if args.func.__code__.co_argcount == 0:
            args.func()
        else:
            args.func(args)

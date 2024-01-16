from datasette import hookimpl
from .enrichment import ShellEnrichment
from .cli import cli


@hookimpl
def register_enrichments(datasette):
    return [ShellEnrichment()]


def main():
    cli()

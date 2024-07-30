import asyncio
import click
import sqlite_utils
import datasette.database
import datasette.app

from wtforms import Form, SelectField, TextAreaField
from wtforms.validators import DataRequired
from wtforms.fields.core import UnboundField
from datasette_enrichments_shell import ShellEnrichment


def create_click_command(form_class):
    "after a database and table are specified, this command dynamically creates a click command based on enrichment form for that pair"

    command_options = [
        click.argument("database-path", type=click.Path(exists=True)),
        click.argument("table-name", type=str, required=False),
    ]

    for field_name, field in form_class.__dict__.items():
        # UnboundField is an internal class which wraps other specific classes
        # probably an internal class, so this is brittle
        if not isinstance(field, UnboundField):
            continue

        option_type = str

        if field.field_class == SelectField:
            option_type = click.Choice(
                [c[0] for c in field.kwargs["choices"]], case_sensitive=False
            )

        field_name = f"--{field_name.replace('_', '-')}"

        option = click.option(
            field_name,
            type=option_type,
            required=any(
                isinstance(v, DataRequired) for v in field.kwargs.get("validators", [])
            ),
            help=field.kwargs.get("description", None),
        )
        command_options.append(option)

    def decorator(f):
        for option in reversed(command_options):
            f = option(f)
        return click.command(f)

    return decorator


def dynamic_command_func(**form_data):
    breakpoint()


# TODO if --help is passed WITH table + database, we should show the help for dynamically created command
@click.command()
@click.argument("database-path", type=click.Path(exists=True))
@click.argument("table-name", type=str, required=False)
def cli(database_path, table_name, **kwargs):
    "Run an enrichment over the command line"

    if not table_name:
        db = sqlite_utils.Database(database_path)
        tables = db.table_names()
        click.echo("No table name provided. Please choose from the following:\n")
        click.echo("\n".join(tables))
        return

    ds = datasette.app.Datasette()
    db = datasette.database.Database(ds, path=database_path)
    ds.add_database(db)

    form = asyncio.run(
        ShellEnrichment().get_config_form(
            db=db,
            table=table_name,
        )
    )

    dynamic_command = create_click_command(form)(dynamic_command_func)

    # Get current context
    ctx = click.get_current_context()
    prog_name = ctx.command_path
    args = ctx.args

    import sys

    extracted_args = sys.argv[1:]
    if len(extracted_args) == 2:
        extracted_args.append("--help")

    dynamic_command(args=extracted_args, prog_name=prog_name)

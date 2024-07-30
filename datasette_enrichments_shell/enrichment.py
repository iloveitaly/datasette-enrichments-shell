import asyncio
import subprocess
from datasette import hookimpl
import sqlite_utils
import json
from datasette_enrichments import Enrichment
from typing import TYPE_CHECKING

# this prevents infinite loading loops
if TYPE_CHECKING:
    from datasette.app import Datasette
    from datasette.database import Database

from wtforms import SelectField, Form, TextAreaField, StringField
from wtforms.validators import DataRequired, ValidationError


@hookimpl
def register_enrichments(datasette):
    return [ShellEnrichment()]


class ShellEnrichment(Enrichment):
    name = "Shell Execution"
    slug = "shell"
    description = "Execute a shell command and send the output to a cell"
    log_traceback = True

    # the batch size is run in parallel
    batch_size = 10

    async def get_config_form(self, db: "Database", table: str):
        columns = await db.table_columns(table)

        class ConfigForm(Form):
            input_mode = SelectField(
                "input mode",
                choices=[
                    ("json", "Pass JSON blob to command"),
                    ("single", "Pick a single column to pass into the command"),
                ],
                validators=[DataRequired(message="A input mode is required.")],
            )

            command = TextAreaField(
                "Command",
                render_kw={
                    "placeholder": f"/path/to/shell\njq -r '.email | xargs -I{{}} echo {{}}'"
                },
                validators=[DataRequired(message="A regular expression is required.")],
            )

            single_column = SelectField(
                "Single column",
                description="If input mode is 'single' only this column will be passed to the command",
                choices=[(column, column) for column in columns],
            )

            # TODO
            output_column = TextAreaField(
                "Output column",
                description="The name of the column to store the output in (can be an existing column)",
            )

        return ConfigForm

    # async def initialize(self, datasette, db, table, config):
    #     # Ensure column exists
    #     output_column = config["output_column"]

    #     def add_column_if_not_exists(conn):
    #         db = sqlite_utils.Database(conn)
    #         if output_column not in db[table].columns_dict:
    #             db[table].add_column(output_column, str)

    #     await db.execute_write_fn(add_column_if_not_exists)

    async def enrich_batch(
        self,
        datasette: "Datasette",
        db: "Database",
        table: str,
        rows: list,
        pks: list,
        config: dict,
        job_id: int,
    ):
        command = config["command"]
        single_column = config["single_column"]
        input_mode = config["input_mode"]
        output_column = config["output_column"]

        if not pks:
            pks = ["rowid"]

        # does the output column exist?
        if output_column not in await db.table_columns(table):
            print("Adding output column")
            await db.execute_write(
                "alter table [{table}] add column [{output_column}] text".format(
                    table=table, output_column=output_column
                )
            )
        else:
            print("output column already exists")

        async def process_row(row):
            # let's check if there's already content in the output column
            if output_column in row and row[output_column]:
                print("output column already has content")
                return

            input_data = self._prepare_input(
                row=row,
                input_mode=input_mode,
                single_column=single_column,
                database=db,
                table=table,
            ).encode("utf-8")

            process = await asyncio.create_subprocess_shell(
                command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                # shell=True,
                # TODO we should allow this to be customized
                # executable="/bin/zsh",
            )

            stdout, stderr = await process.communicate(input=input_data)
            is_successful = process.returncode == 0

            if not is_successful:
                # TODO better way to display errors?
                print(stderr.decode("utf-8"))

                await self.log_error(
                    db,
                    job_id,
                    # TODO this looks wrong :/ Maybe `pks_for_rows`?
                    [row[pks[0]]],
                    f"Command exited with error code {process.returncode}",
                )

                return

            output = stdout.decode("utf-8")

            if not output:
                print("output is empty")
                return

            print(f"Updating row {row[pks[0]]} with output {output}")

            await db.execute_write(
                "update [{table}] set [{output_column}] = ? where {wheres}".format(
                    table=table,
                    output_column=output_column,
                    wheres=" and ".join('"{}" = ?'.format(pk) for pk in pks),
                ),
                # ids is an array of keys to properly handle compound pks
                [output] + list(row[pk] for pk in pks),
            )

        async with asyncio.TaskGroup() as tg:
            for row in rows:
                tg.create_task(process_row(row))

    def _prepare_input(self, *, row, input_mode, single_column, database, table):
        if input_mode == "json":
            return json.dumps(
                {
                    # include database path and table name as _meta fields
                    # this would enable any commands run to reference the database being modified
                    "_meta": {
                        "database": database.path,
                        "table": table,
                    }
                }
                | row
            )
        elif input_mode == "single":
            return row[single_column]
        else:
            raise Exception(f"Unknown input mode: {input_mode}")

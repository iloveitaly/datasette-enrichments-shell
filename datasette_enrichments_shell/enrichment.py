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
                    "placeholder": "Use (?P<name>pattern) for named capture groups"
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

    async def enrich_batch(
        self,
        db: "Database",
        table: str,
        rows: list[dict],
        pks: list[str],
        config: dict,
    ):
        command = config["command"]
        single_column = config["single_column"]
        input_mode = config["input_mode"]
        output_column = config["output_column"]

        if not pks:
            pks = ["rowid"]

        to_update = []

        for row in rows:
            # let's check if there's already content in the output column
            if output_column in row and row[output_column]:
                continue

            input_data = self._prepare_input(
                row=row,
                input_mode=input_mode,
                single_column=single_column,
                database=db,
                table=table,
            ).encode("utf-8")

            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=True,
                executable="/bin/zsh",
            )

            stdout, stderr = process.communicate(input=input_data)
            is_successful = process.returncode == 0

            if not is_successful:
                # TODO better way to display errors?
                print(stderr.decode("utf-8"))
                continue

            output = stdout.decode("utf-8")
            # ids is an array of keys to properly handle compound pks
            ids = [row[pk] for pk in pks]
            to_update.append((ids, {output_column: output}))

        if to_update:

            def fn(conn):
                db = sqlite_utils.Database(conn)
                for ids, values in to_update:
                    db[table].update(ids, values, alter=True)

            await db.execute_write_fn(fn, block=True)

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

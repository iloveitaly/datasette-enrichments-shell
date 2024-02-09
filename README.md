# datasette-enrichments-shell

Something I've always wanted to do is to be able to easily run a map reduce operation on a CSV. This is something that all the nifty command line tools (zq, jq, etc) don't allow you to do.

However, I noticed that Datasette recently added the ability to write enrichment plugins. I hacked together this enrichment plugin that allows you to run an arbitrary shell script and if the script was successful, save the resulting output to a new column.

## Installation

Install this plugin in the same environment as Datasette.

```shell
datasette install -U datasette-enrichments-shell
```

Or, if you are hacking on this locally:

```shell
datasette install -U ~/Projects/python/datasette-enrichments-shell
```

## Usage

After installing the plugin, you'll see the shell enrichment option in the UI. You can use this to run a shell command and save the output to a new column.

### Examples

Here's how to test a shell script before plugging it into the web UI:

```shell
echo '{"rowid": 1, "firstName": "Forest", "lastName": "Tree"}' | \
jq -r '"-p firstName \(.firstName) -p lastName \(.lastName)"' | \
xargs -I {} /Users/mike/.asdf/shims/sqlite-utils query email_personal.db "SELECT * FROM address_book WHERE first_name = :firstName AND last_name = :lastName LIMIT 1" {}
```

## Development

To set up this plugin locally, first checkout the code. Then create a new virtual environment:

```bash
cd datasette-enrichments-shell
poetry install
```

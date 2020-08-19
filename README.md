# jira-updater #

This is a tool write in python3 to help to follow whamcloud tickets for the
CEA purpose.
It uses a csv "database" to follow some whamcloud jira tickets. The update
function will synchronize the csv file data to the remote Jira database
and check for new tickets matching CEA needs.
This tool enables to create sheets for tickets to add more information.

## Installation ##

This tool use python3 and jira API for python
(https://jira.readthedocs.io/en/master/installation.html).

To install python module for the Jira API:
`pip install jira`
or `pip3 install jira`

## Usages ##

### Initialisation ###

To initialize the database, you can create a csv file (here csvfile.csv) with
one column 'key' and add the some tickets id that you want to follow.

Then to initialize the csv columns with remote database, you can execute:
`./jira-updater.py csvfile.csv update --force --no-news`
(--force will force the sync of the existing tickets, --no-news will not check
for new tickets)

#### Note ####
You can then add columns that you need in the database.

### Update ###

`./jira-updater.py <csvfile> update <opt>`

The command above will update jira row data in the csv file.
When option "--force/-f" is specified, it will try to update all the tickets in
csv file. If not it will only check row with column 'trackState' with value set
to "Follow" or "Updated" and it will update the row only if the date in column
'updated' is inferior to the date of the 'updated' field in the remote database.

At the end of row update process it will set the columns 'trackState' to
'Updated' for each updated row.

If the option "--no-news/-n" is not specified, the tool will try to search and
add new tickets in the csv matching the following JQL request:
```
type = Bug 
    AND priority > Minor 
    AND project = Lustre 
    AND created >= "<lastCreated>" 
    AND (affectedVersion ~ "*Lustre 2.12*" 
          OR affectedVersion is EMPTY) 
    ORDER BY created DESC)
```

*lastCreated*: the variable is the maximum of dates in the csv column 'created'.

### Edit Ticket Sheet ###

`./jira-updater.py <csvfile> edit <opt> <ticketId>

The following command will add or edit a ticket sheet for a Jira ticket. It will
open an editor (specified in EDITOR env variable) to edit the sheet.

The default directory path for ticket sheets is: `<parent_csvfile_dir>/sheets`.
You can specified a specific dir for sheets with option "--sheetDir/-d".

If the option "--no-update/-n" is not specified fields of sheet matching colmns
in csv will be update with csv data before editing it with editor.

### Sheet Format ###

The ticket sheet format uses markdown format as specified below:
```
# LU-XXXX : summary #

#Comment1
## Field 1 ##
Value of field 1
Value of field 1

Value of field 1

## Field 2 ##
Value of field 2

## Field 3 ##
Value of field 3
```

#### Note ####
You can use markdown inside sheet fields, but try to avoid using quotes.

## Author ##

Etienne AUJAMES <eaujames@ddn.com>


# jira-tracker #

This is a tool write in python3 to help to follow whamcloud tickets for the
CEA purpose.  
It uses a csv "database" to follow some whamcloud Jira tickets. The update
function will synchronize the CSV file data to the remote Jira database
and check for new tickets matching CEA needs.  
This tool enables to create sheets for tickets to add more information.

## Installation ##

This tool use python3 and jira API for python
([Jira API documentation](https://jira.readthedocs.io/en/master/installation.html)).

To install python module for the Jira API:  
`pip install jira`  
or `pip3 install jira`

## Usages ##

### Initialisation ###

To initialize the database, you can create a csv file (here csvfile.csv) with
one column 'key' and add the some tickets id that you want to follow.

Then to initialize the csv columns with remote database, you can execute:  
`./jira-tracker.py csvfile.csv update --force --no-news`  
(--force will force the sync of the existing tickets, --no-news will not check
for new tickets)

#### Note ####
You can then add columns that you need in the database.

### Update ###

`./jira-tracker.py <csvfile> update <opt>`

The command above will update jira row data in the csv file.  
When option "--force/-f" is specified, it will try to update all the tickets in
csv file. If not it will only check row with column 'trackstate' with value set
to "Follow" or "Updated" and it will update the row only if the date in column
'updated' is inferior to the date of the 'updated' field in the remote database.

At the end of row update process it will set the columns 'trackstate' to
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

```
jira-tracker.py inFile edit [-h] [-d SHEETDIR] [-n] [--updated] [--new]
                            [-f FILTER] [-a]
                            [keys [keys ...]]
```

The command above will add or edit a ticket sheet for a Jira ticket. It will
open an editor (specified in EDITOR env variable) to edit the sheet.

The default directory path for ticket sheets is: `<parent_csvfile_dir>/sheets`.
You can specified a specific dir for sheets with option "--sheetDir/-d".

If the option "--no-update/-n" is not specified, the fields of sheet matching
columns in csv will be update with csv data before editing it with editor.

If the sheet does not exist, the script will use the template file
"sheet.template" instead to generate a temporary sheet.

If the Jira ticket does not exist in the CSV file, the script will try to
request information to the Jira database and create a temporary sheet fill with
the Jira data.  
Then it will create new line in the CSV file with the information gather from
Jira and from the sheet.

### Mail command ###

```
./jira-tracker.py inFile mail [-h] [-d SHEETDIR] [-o OUTFILE] [--updated]
                         [--new] [-f FILTER] [-a]
                         [keys [keys ...]]
```
The command above is used to format with markdown a group of sheets in a compact
way. The generated output can be uses for exemple in a email, for exemple, to
warn about new tickets seen.  

The sheets can be selected directly by ticket ID (keys arguments) or by filters
(ex: --new).

If the "-o" option is use, the script will generate the output formated in the
OUTFILE file and then try to open it with an editor (in EDITOR env variable).  
This could be useful if the editor is a markdown reader because this will create
a preview that could be "copy/paste" into a HTML mail.

If the "-o" option is not use, the script will use "STDOUT" to display the
generated output.

### Show command ###

```
jira-tracker.py inFile show [-h] [-l] [-i] [-c COLS] [--csv] [--all]
                            [--updated] [--new] [-f FILTER] [-a]
                            [keys [keys ...]]
```

The command above is use to display some data from the CSV file.

The CSV line can be selected by filter (ex: --new) or directly by ticket ID
("keys" arguments).

The option "--link" will generate an Jira link to see the tickets selected
drectly on Jira.

The option "--ids" will display the list of the tickets id found.

The option "--cols" enable to choose the columns to display (by default all the
colums are selected)  
`ex: --cols comment,trackstate`

The option "--csv" will format the output in CSV.

By default the output is formated like below:
```
LU-XXXX :
	Summary : <summary>
	Status : Reopened
	Resolution :
	Created : 2018-10-02 17:09
	Updated : 2020-06-06 00:46
	Interest : 1
	Trackstate : Follow
	Jiraurl : https://jira.whamcloud.com/browse/LU-XXXX
	Comment :
	  <comment_line>
	  <comment_line>
--
```

### Modify command ###

```
usage: jira-tracker.py inFile modify [-h] [-k KEYS] [--updated] [--new]
                                     [-f FILTER] [-a]
                                     values [values ...]
```

The command above is use to modify directly some values in CSV files.

The CSV line to modify can be selected by filter (ex: --new) or directly by
ticket ID ("keys" arguments).

The values to modify are specified by the arguments "values".  
ex: `'trackstate=New' 'comment=Test test'`  
The arguments above will specified to set the column 'trackstate' and 'comment'
respectively to 'New' and 'Test test' for all the lines selected.

#### Warning ####
This command will not modify values on the sheets

### Filter options ###

The filters options "--new", "--updated", "--filter FILTER" and "--filter-and"
are use to select some lines in the CSV database.

The option "--filter `col`=`val`" is use to select all the line with their
column named "`col`" matching the specified "`val`".  
ex: `--filter trackstate=Follow`

The options "--new" and "--updated" are respectively aliases of "--filter
trackstate=New" and "--filter trackstate=Updated"

Several filters option can be used for a command. The selected line  by
default will be the reunion ("or") between all the line selected by all the
filters.  
If the option "--filter-and" is used, the selected lines will be the lines that
match all the filters ("and" between the filters).

## Sheet Format ##

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


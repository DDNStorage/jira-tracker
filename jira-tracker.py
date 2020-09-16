#!/usr/bin/python3

import argparse
import csv
import sys
import os
import shutil
import tempfile
import re
import urllib.parse
from datetime import datetime
from datetime import timezone
from datetime import timedelta
from collections import OrderedDict
from jira import JIRA

# Config
class config():
    jiraURLRoot = "https://jira.whamcloud.com"
    jiraFields = [
            "key",
            "summary",
            "status",
            "resolution",
            "created",
            "updated"
            ]
    localFields = [
            "interest",
            "trackstate",
            "jiraurl",
            "comment",
            ]
    dateFields = [
            "created",
            "updated",
            ]

    def mergeFields(self, field2Merge):
        confFields = self.jiraFields + self.localFields
        diffList = sorted( set(confFields) - set(field2Merge),
                key=confFields.index)
        return list(field2Merge) + diffList

def debug(strDebug):
    print(strDebug, file=sys.stderr)

def parseArgs():
    parser = argparse.ArgumentParser()
    parser.add_argument("inFile", type=argparse.FileType('r'),
            help="CSV database path")
    subParsers = parser.add_subparsers(dest='action',
            help="Action on CSV database")

    # Update
    updateParse = subParsers.add_parser('update', help="Update Database")
    updateParse.add_argument( "-o", "--outFile",
            help="CSV database out path")
    updateParse.add_argument( "-n", "--no-news", action='store_true',
            help="Do not check for new tickets")
    updateParse.add_argument( "-f", "--force", action='store_true',
            help="Force to update each row of CSV files")

    # Search
    searchParse = subParsers.add_parser('search',
            help="Search in database")
    searchParse.add_argument("searchCmd",
            help="Jira search string")

    # Mail
    mailParse = subParsers.add_parser('mail',
            help="Generate output for a mail")
    mailParse.add_argument( "-d", "--sheetDir",
            help="Directory where is store ticket sheets")
    mailParse.add_argument( "-o", "--outFile", type=argparse.FileType('w'),
            help="Mail output file", default=sys.stdout)
    mailParse.add_argument("keys", nargs='*',
            help="Ticket key of the sheet")
    ##   Filters
    mailParse.add_argument("--updated", action='store_true',
            help="Select all updated tickets")
    mailParse.add_argument("--new", action='store_true',
            help="Select all new tickets")
    mailParse.add_argument("-f", "--filter", action='append', default=list(),
            help="Ticket filter. Format: <column>=<patern_val>")
    mailParse.add_argument( "-a", "--filter-and", action='store_true',
            help="Match reunion of filters. By default match union")

    # Edit sheet
    editParser = subParsers.add_parser('edit',
            help="Edit jira ticket sheet")
    editParser.add_argument("-d", "--sheetDir",
            help="Directory where is store ticket sheets")
    editParser.add_argument("-n", "--no-update", action='store_true',
            help="Do not update sheet with field in csv")
    editParser.add_argument("keys", nargs='*',
            help="Ticket key of the sheet")
    ##   Filters
    editParser.add_argument("--updated", action='store_true',
            help="Select all updated tickets")
    editParser.add_argument( "--new", action='store_true',
            help="Select all new tickets")
    editParser.add_argument( "-f", "--filter", action='append', default=list(),
            help="Ticket filter. Format: <column>=<patern_val>")
    editParser.add_argument( "-a", "--filter-and", action='store_true',
            help="Match reunion of filters. By default match union")

    # Modify values
    setParser = subParsers.add_parser('modify',
            help="Modify entries in the CSV")
    setParser.add_argument("-k", "--keys",
            help="Ticket keys to select (separate with comma)")
    setParser.add_argument("values", nargs='+',
            help="Values to modify (ex: 'trackstate=New' 'comment=Test test')")
    ##   Filters
    setParser.add_argument("--updated", action='store_true',
            help="Select all updated tickets")
    setParser.add_argument("--new", action='store_true',
            help="Select all new tickets")
    setParser.add_argument( "-f", "--filter", action='append', default=list(),
            help="Ticket filter. Format: <column>=<patern_val>")
    setParser.add_argument( "-a", "--filter-and", action='store_true',
            help="Match reunion of filters. By default match union")

    # Show
    showParser = subParsers.add_parser('show',
            help="Select, format and display database entries")
    showParser.add_argument( "-l", "--link", action='store_true',
            help="Display only the Jira link to see tikets online")
    showParser.add_argument( "-i", "--ids", action='store_true',
            help="Display only tickets IDs")
    showParser.add_argument( "-c", "--cols",
            help="Select colums to display (default all): -c comment,trackstate")
    showParser.add_argument("--csv", action='store_true',
            help="Display lines in csv format")
    showParser.add_argument("keys", nargs='*',
            help="Ticket key of the sheet")
    ##   Filters
    showParser.add_argument("--all", action='store_true',
            help="Select all tickets")
    showParser.add_argument("--updated", action='store_true',
            help="Select all updated tickets")
    showParser.add_argument("--new", action='store_true',
            help="Select all new tickets")
    showParser.add_argument( "-f", "--filter", action='append', default=list(),
            help="Ticket filter. Format: <column>=<patern_val>")
    showParser.add_argument( "-a", "--filter-and", action='store_true',
            help="Match reunion of filters. By default match union")

    return parser.parse_args()

class dateCSV():
    strCsvFormat = '%Y-%m-%d %H:%M'
    date = None

    def __init__(self, date):
        self.date = date

    def __str__(self):
        return self.date.strftime(self.strCsvFormat)

    def fromJira(str2Conv):
        try:
            date = datetime.strptime(str2Conv, '%Y-%m-%dT%H:%M:%S.%f%z')
            return dateCSV(date)
        except:
            debug("Unable to convert '%s'" % str2Conv)
            return str2Conv

    def fromCsv(str2Conv):
        try:
            date = datetime.strptime(str2Conv+'+0000', dateCSV.strCsvFormat+'%z')
            return dateCSV(date)
        except:
            pass

        try:
            date = datetime.strptime(str2Conv+'+0000',  '%m/%d/%Y %H:%M%z')
            return dateCSV(date)
        except:
            debug("Unable to convert '%s'" % str2Conv)
            return str2Conv

class action():
    _conf = None
    _jira = None
    _files = { 'in' : None, 'out' : None }

    def __init__(self, conf):
        self._conf = conf

    def names(self):
        return list(self.funcs.keys())

    def runAction(self, args):
        ret = True
        if args.action in self.funcs:
            func = self.funcs[args.action]
            ret = func(self, args)
        else:
            debug("Action callback not found: %s" % args.action)
            ret = False
        return ret

    def update(self, args):
        if not self._initJiraApi():
            return False

        csvIn = self._initCsvReader(args.inFile)
        if csvIn == None:
            return False

        outFields = conf.mergeFields(csvIn.fieldnames)
        csvOut = self._initCsvWriter(args.outFile, outFields)
        if csvOut == None:
            return False

        # stat var
        rowNbr = 1
        updatedKeys = list()
        newKeys = list()
        lastCreated = dateCSV(datetime(1900,1,1, tzinfo=timezone.utc))

        # Update existing row
        for rowIn in csvIn:
            rowNbr+=1
            if 'key' not in rowIn or not self._checkKeyFormat(rowIn['key']):
                debug("Invalid 'key' at %s:%d" % (args.inFile.name, rowNbr))
                continue

            self._convertCvsDate(rowIn)
            rowOut = self._initFields(rowIn, outFields)

            if self._jira.update(rowOut, args.force):
                updatedKeys.append(rowOut['key'])
                debug("Update row %d (%s)" % (rowNbr, rowOut['key']))

            if isinstance(rowOut['created'], dateCSV):
                lastCreated = dateCSV(max(lastCreated.date, rowOut['created'].date))
            try:
                csvOut.writerow(rowOut)
            except Exception as inst:
                debug("Fail to write csv row %d: %s" % (rowNbr, inst))
                return False

        # Adding new row
        if not args.no_news:
            debug("Creation date of the last entry in the database: %s" % lastCreated)
            for jiraData in self._jira.news(lastCreated):
                rowNbr+=1
                rowOut = self._initFields(jiraData, outFields)
                debug("Add new row %d (%s)" % (rowNbr, rowOut['key']))

                try:
                    csvOut.writerow(rowOut)
                except Exception as inst:
                    debug("Fail to write csv row %d: %s" % (rowNbr, inst))
                    return False

                newKeys.append(rowOut['key'])

        # Clean
        del csvIn, csvOut
        if not self._save(args.outFile):
            return False

        # Report
        debug("\nNumber of updated rows: %d/%d," % (len(updatedKeys), rowNbr-1))
        debug(" " + jiraUpdate.link(self._conf.jiraURLRoot, updatedKeys))
        debug("Number of new rows: %d/%d," % (len(newKeys), rowNbr-1))
        debug(" " + jiraUpdate.link(self._conf.jiraURLRoot, newKeys))

        return True

    def edit(self, args):
        csvIn = self._initCsvReader(args.inFile)
        if csvIn == None:
            return False

        keys = set()
        for key in args.keys:
            if self._checkKeyFormat(key):
                keys.add(key)
            else:
                debug("Invalid key id: %s" % key)

        # Add keys matching filters
        keys.update(self._searchKeysFromArg(args))

        if len(keys) <= 0:
            debug('No sheet to be edited')
            return False

        debug("Editing keys: %s" % ', '.join(keys))

        csvOut = self._initCsvWriter(None, csvIn.fieldnames)
        if csvOut == None:
            return False

        sheetDir = args.sheetDir
        if not sheetDir:
            sheetDir = os.path.dirname(args.inFile.name)
            if not sheetDir:
                sheetDir = '.'
            sheetDir += '/sheets'

        if not os.path.isdir(sheetDir):
            try:
                os.mkdir(sheetDir)
            except Exception as inst:
                debug("Failed to create %s: %s" % (sheetDir, inst))
                return False

        for rowIn in csvIn:
            if 'key' in rowIn and rowIn['key'] in keys:
                keys.remove(rowIn['key'])
                if not self._editSheet(rowIn['key'],
                        sheetDir,
                        rowIn,
                        update=(not args.no_update)):
                    return False

            csvOut.writerow(rowIn)

        for key in keys:
            debug("Ticket key \"%s\" not found in %s" % (key, args.inFile.name))
            debug("Try to add %s in database" % key)

            outFields = conf.mergeFields(rowIn.keys())
            newRow = self._initFields({'key': key}, outFields)

            if self._initJiraApi():
                self._jira.update(newRow, True)
            if not self._editSheet(newRow['key'], sheetDir, newRow,update=True):
                return False

            csvOut.writerow({k:newRow[k] for k in csvIn.fieldnames})

        del csvIn, csvOut
        return self._save(None)

    def search(self, args):
        print("search")

    def mail(self, args):
        csvIn = self._initCsvReader(args.inFile)
        if csvIn == None or not 'key' in csvIn.fieldnames:
            return False
        self._files['out'] = args.outFile
        fdOut = args.outFile

        keys = set()
        for key in args.keys:
            if self._checkKeyFormat(key):
                keys.add(key)
            else:
                debug("Invalid key id: %s" % key)

        # Add keys matching filters
        keys.update(self._searchKeysFromArg(args))

        if len(keys) <= 0:
            debug('No sheet to display')
            return False

        debug("Display sheets with keys: %s" % ', '.join(keys))

        sheetDir = args.sheetDir
        if not sheetDir:
            sheetDir = os.path.dirname(args.inFile.name)
            if not sheetDir:
                sheetDir = '.'
            sheetDir += '/sheets'

        notFound = list()
        for key in keys:
            sheet = sheetObj.open(key, sheetDir, template=False)
            if sheet is None:
                notFound.append(key)
            else:
                fdOut.write("%s--  \n\n" % sheet)

        if len(notFound) > 0:
            debug("Warning: following sheet not found: %s" % ', '.join(notFound))

        fdOut.flush()
        if fdOut.name != "<stdout>":
            self._openWithEditor(fdOut.name)

        return True

    def modify(self, args):
        csvIn = self._initCsvReader(args.inFile)
        if csvIn == None:
            return False

        keys = set()
        if args.keys:
            for key in args.keys.split(','):
                if self._checkKeyFormat(key):
                    keys.add(key.strip())
                else:
                    debug("Invalid key id: %s" % key)

        # Add keys matching filters
        keys.update(self._searchKeysFromArg(args))

        if len(keys) <= 0:
            debug('No ticket ID entries to modify')
            return False

        # Get value to modify
        valuesDict = dict()
        for value in args.values:
            splitVal = value.split('=', 1)
            if len(splitVal) != 2:
                debug("Malformed value string '%s'" % value)
            elif not splitVal[0] in csvIn.fieldnames:
                debug("Unknown value key '%s'" % splitVal[0])
            else:
                valuesDict.update({splitVal[0]: splitVal[1]})

        if len(valuesDict) <= 0:
            debug("No value to modify")
            return False

        debug("Modifying keys: %s" % ', '.join(keys))

        csvOut = self._initCsvWriter(None, csvIn.fieldnames)
        if csvOut == None:
            return False

        for row in csvIn:
            if row['key'] in keys:
                keys.remove(row['key'])
                row.update(valuesDict)
            csvOut.writerow(row)

        if len(keys) > 0:
            debug("Unknown ticket IDs: %s" % ', '.join(keys))

        del csvIn, csvOut
        return self._save(None)

    def show(self, args):
        csvIn = self._initCsvReader(args.inFile)
        if csvIn == None or not 'key' in csvIn.fieldnames:
            return False

        keys = set()
        for key in args.keys:
            if self._checkKeyFormat(key):
                keys.add(key)
            else:
                debug("Invalid key id: %s" % key)

        # Add keys matching filters
        keys.update(self._searchKeysFromArg(args))

        if args.link:
            ret = True
            if len(keys) > 0:
                print(jiraUpdate.link(self._conf.jiraURLRoot, list(keys)))
                return True
            debug("No keys selected, use filter or keys for selection")
            return False

        cols = list(csvIn.fieldnames)
        cols.remove('key')
        if args.cols is not None:
            cols = args.cols.split(',')
            cols = [i.strip().lower() for i in cols]

        writer = sys.stdout
        showFct = action._showUser
        if args.ids:
            showFct = action._showId
        elif args.csv:
            writer = self._initCsvWriter(writer, ['key'] + cols)
            showFct = action._showCsv

        for row in csvIn:
            if row['key'] in keys or args.all:
                key = row['key']
                if len(keys) > 0:
                    keys.remove(key)
                showFct(row, cols, writer)

        if args.ids:
            writer.write('\n')

        if len(keys) > 0:
            debug("Unknown ticket IDs: %s" % ', '.join(keys))

        return True

    def _showId(row, cols, writer):
        key = row.setdefault('key', "NA")
        return writer.write("%s " % key)

    def _showCsv(row, cols, writer):
        return writer.writerow({k:row.setdefault(k, "NA") for k in ['key'] + cols})

    def _showUser(row, cols, writer):
        key = row.setdefault('key', "NA")

        writer.write("%s :\n" % key)
        for k in cols:
            writer.write("\t%s : " % k.capitalize())

            field = row.setdefault(k, "NA")
            if len(field) > 80 or field.find("\n") >= 0:
                writer.write("\n\t  ")
            writer.write("%s\n" % field.replace("\n", "\n\t  "))

        writer.write("--\n")

    def _initJiraApi(self):
        if self._jira == None:
            try:
                self._jira = jiraUpdate(conf)
            except Exception as inst:
                debug( "Fail to init JIRA API: %s" % inst)
                return False
        return True

    def _initFields(self, rowIn, outFields):
        rowOut = dict.fromkeys(outFields)
        rowOut.update(rowIn)
        rowOut['key'] = rowOut['key'].strip()

        if not rowOut['jiraurl']:
            rowOut['jiraurl'] = conf.jiraURLRoot + '/browse/' + rowOut['key']
        if not rowOut['trackstate']:
            rowOut['trackstate'] = 'New'
        if not rowOut['interest']:
            rowOut['interest'] = '0'

        return rowOut

    def _searchKeysFromArg(self, args):
        keys = set()
        searchDict = list()
        isOr = True

        if hasattr(args, 'filter_and'):
            isOr = not args.filter_and
        if hasattr(args, 'updated') and args.updated:
            searchDict.append(('trackstate', 'Updated'))
        if hasattr(args, 'new') and args.new:
            searchDict.append(('trackstate', 'New'))

        for fil in args.filter:
            splitFil = fil.split('=', 1)
            if len(splitFil) == 2:
                searchDict.append(tuple(splitFil))
        if len(searchDict) > 0:
            keys.update(self._searchKeys(searchDict, isOr))

        return keys

    def _searchKeys(self, conditions, isOr=True):
        foundKeys = set()
        csvIn = self._resetCsvReader()

        if not 'key' in csvIn.fieldnames:
            return foundKeys

        for row in csvIn:
            isKeyMatch = False
            for cond in conditions:
                k, v = cond
                isKeyMatch = (k in row and row[k] == v)
                if isOr and isKeyMatch:
                    break
                elif not isOr and not isKeyMatch:
                    break

            if isKeyMatch:
                foundKeys.add(row['key'].strip())

        self._resetCsvReader()
        return foundKeys

    def _editSheet(self, key, sheetDir, rowIn, update=True, editor=True):
        ret = True

        # Open temp sheet
        sheet2Edit = sheetObj.open(key, sheetDir, template=True)
        if sheet2Edit == None:
            return ret

        outFields = conf.mergeFields(rowIn.keys())
        rowOut = self._initFields(rowIn, outFields)

        ret = sheet2Edit.initWrite(rowOut, update=update)

        # Open with editor
        if editor:
            ret = self._openWithEditor(sheet2Edit.name(temp=True))

        isChange = False
        if editor and ret:
            # Ask for save
            prompt = input('Save(Y/n), Abort(a)?:')
            if not prompt or prompt.lower() == 'y':
                ret = sheet2Edit.save()
                isChange = ret
            elif prompt.lower() == 'a':
                debug("Abort edition")
                ret = False

        elif not editor:
            ret = sheet2Edit.save()

        if isChange:
            # Re-parse sheet to update rowIn
            dataSheet = sheet2Edit.parse()
            dataSheet.pop('key')
            dataSheet.pop('summary')
            for i in rowIn:
                if (i in dataSheet.keys()
                        and dataSheet[i]
                        and rowIn[i] != dataSheet[i]):
                    debug("- Update columns \"%s\" from sheet" % i)
                    rowIn[i] = dataSheet[i]

        if ret and 'trackstate' in rowIn:
            props = {'u': 'Updated', 'f':'Follow', 'c': 'Close'}
            prompt = input("Change trackstate \"%s\"?\n" % rowIn['trackstate']
                    + ', '.join(["%s(%s)" % (props[k], k) for k in props])
                    + ': ')
            if prompt and prompt.lower() in props:
                rowIn['trackstate'] = props[prompt]

        sheet2Edit.close()
        return ret

    def _openWithEditor(self, fileName):
        editor = 'vim'
        if 'EDITOR' in os.environ:
            editor = os.environ['EDITOR']

        return (0 == os.system(editor + " '" + fileName + "'"))

    def _checkKeyFormat(self, key):
        p = re.compile('^[ \t]*[A-Z]+-[0-9]+[ \t]*$')
        return p.match(key)

    def _convertCvsDate(self, row):
        # Convert dates
        for i in self._conf.dateFields:
            if i in row and row[i]:
                row[i] = dateCSV.fromCsv(row[i])

    def _initCsvWriter(self, file, fields):
        try:
            if not file:
                updateOutPrefix = os.path.basename(__file__) + '.out.'
                self._files['out'] = tempfile.NamedTemporaryFile(mode='x',
                        prefix=updateOutPrefix, suffix=".csv")
            elif hasattr(file, 'write'):
                self._files['out'] = file
            else:
                self._files['out'] = open(file, 'w')

            csvOut = csv.DictWriter(self._files['out'], fields,
                    quoting=csv.QUOTE_NONNUMERIC)
            csvOut.writeheader()
        except Exception as inst:
            debug("Fail to create CSV output file: %s" % inst)
            return None

        return csvOut

    def _initCsvReader(self, fdIn):
        self._files['in'] = fdIn
        try:
            fdIn.seek(0)
            csvIn = csv.DictReader(fdIn)
        except Exception as inst:
            debug("Fail to open CSV input file: %s" % inst)
            return None

        return csvIn

    def _resetCsvReader(self):
        fdIn = self._files['in']
        try:
            fdIn.seek(0)
            csvIn = csv.DictReader(fdIn)
        except Exception as inst:
            debug("Fail to open CSV input file: %s" % inst)
            return None

        return csvIn

    def _save(self, outFile):
        ret = True
        if not outFile:
            # user use a temp file
            try:
                self._files['in'].close()
                self._files['out'].flush()
                shutil.copyfile(self._files['in'].name,
                        self._files['in'].name + '.old')
                shutil.copyfile(self._files['out'].name, self._files['in'].name)
                self._files['out'].close()
            except Exception as inst:
                debug("Failed to save %s: %s" % (self._files['in'].name, inst))
                ret = False
        return ret

    def _clean(self):
        for k, f in self._files.items():
            if f != None:
                f.close()

    def __del__(self):
        self._clean()

    funcs = {
            "update" : update,
            "search" : search,
            "mail"   : mail,
            "edit"   : edit,
            "modify" : modify,
            "show"   : show,
            }

class jiraUpdate():
    _conf = None
    _jiraApi = None
    _UpdatedJQL = 'key = "%s" AND updated > "%s" '
    _CreatedJQL = ('type = Bug '
            + 'AND priority > Minor '
            + 'AND project = Lustre '
            + 'AND created >= "%s" '
            + 'AND (affectedVersion ~ "*Lustre 2.12*" '
            +       'OR affectedVersion is EMPTY) '
            + 'ORDER BY created DESC')

    def __init__(self, conf):
        self._conf = conf
        self._jiraApi = JIRA(conf.jiraURLRoot)

    def update(self, row, force=False):
        issueArr = list()
        ret = False
        cmd = None
        fields = ','.join(self._conf.jiraFields)

        try:
            if force:
                cmd = row['key']
                issueArr.append(self._jiraApi.issue( cmd,
                    fields=fields));

            elif (row['trackstate'] in ['Follow', 'Updated']
                    and isinstance(row['updated'], dateCSV)):
                date = dateCSV(row['updated'].date + timedelta(0,60))
                cmd = self._UpdatedJQL % (row['key'], date)
                issueArr = self._jiraApi.search_issues( cmd, maxResults=1,
                        fields=fields);
        except Exception as inst:
            debug('JIRA request fail (cmd="%s"): %s' % (cmd, inst))

        if len(issueArr) > 0:
            self._updateDict(issueArr[0], row)
            row['trackstate'] = 'Updated'
            ret = True

        return ret

    def news(self, lastCreatedDate):
        date = dateCSV(lastCreatedDate.date + timedelta(0,60))
        jql = self._CreatedJQL % date
        return self.search(jql)

    def search(self, jql):
        issueArr = list()
        retArr = list()
        fields = ','.join(self._conf.jiraFields)

        try:
            issueArr = self._jiraApi.search_issues( jql, maxResults=50000,
                    fields=fields);
        except Exception as inst:
            debug('JIRA request fail (jql="%s"): %s' % (jql, inst))

        for issue in issueArr:
            dictIssue = {'key' : issue.key}
            self._updateDict(issue, dictIssue)
            retArr.append(dictIssue)

        return retArr

    def link(urlRoot, issueIds):
        link = ''
        if len(issueIds) > 0:
            params = {
                    'maxResults' : 50000,
                    'jql' : 'key in (%s)' % ','.join(issueIds)
                    }
            link = (urlRoot
                    + '/browse/%s?' % issueIds[0]
                    + urllib.parse.urlencode(params))

        return link

    def _updateDict(self, jiraObj, dict2Up):
        fields = set(self._conf.jiraFields)
        fields.remove('key')

        for i in fields:
            dict2Up[i] = getattr(jiraObj.fields, i)

        # Convert dates
        for i in self._conf.dateFields:
            dict2Up[i] = dateCSV.fromJira(dict2Up[i])

class sheetObj:
    _fileTemp = None
    _fileRead = None
    _key = None
    _realName = None

    def __init__(self, fd, key, realName):
        self._fileRead = fd
        self._realName = realName
        self._key = key

    def open(keyId, path, template=False):
        sheet = None
        realName = path + '/' + keyId + '.md'
        try:
            sheetFile = open(realName, 'r')
            debug("Existing sheet found for %s" % keyId)
        except:
            debug("No existing file found for %s" % keyId)
            if template:
                debug("Use template instead")
                sheetFile = sheetObj.openTemplate()
            else:
                return sheet

        if sheetFile != None:
            sheet = sheetObj(sheetFile, keyId, realName)

        return sheet

    def name(self, temp=False):
        if temp:
            return self._fileTemp.name
        return self._realName

    def initWrite(self, fields, update=True):
        ret = True
        try:
            self._fileTemp = tempfile.NamedTemporaryFile(mode='x',
                    prefix=self._key+'out', suffix=".md")
        except Exception as inst:
            debug("Unable to open a temp sheet for %s: %s" % (self._key, inst))
            ret = False

        if update:
            ret = self.update(fields)
        else:
            ret = self._copy()

        return ret

    def update(self, fields):
        sheetData = self.parse()

        if sheetData == None:
            return False

        for i in sheetData:
            if i in fields and fields[i]:
                    sheetData[i] = fields[i]

        return self._writeData2Sheet(sheetData)

    def parse(self):
        dataSheet = OrderedDict()
        line = ""
        nextLine = ""
        commentIdx = 0
        key = ""

        fileIn = self._fileRead
        fileIn.seek(0)

        for line in fileIn:
            key, summary = self._parseHeader(line)
            if key:
                if key != self._key:
                    debug("Sheet key in header not matching")
                dataSheet['key'] = key
                dataSheet['summary'] = summary
                break

        if not key:
            debug("No header found in sheet")
            return None

        try:
            line = next(fileIn)
        except StopIteration:
            debug("No fields in the sheet")
            return None

        for nextLine in fileIn:
            comment = self._parseComment(line)
            if comment:
                dataSheet['sheetComment%d' % commentIdx] = comment
                commentIdx += 1
            else:
                field = self._parseField(line)
                if field:
                    value, line, nextLine = self._getValue(line, nextLine)
                    dataSheet[field.lower()] = value

            line = nextLine

        # Parse last line
        comment = self._parseComment(nextLine)
        if comment:
            dataSheet['sheetComment%d' % commentIdx] = comment
        else:
            field = self._parseField(nextLine)
            if field:
                dataSheet[field] = ""

        return dataSheet

    def __str__(self):
        data = self.parse()
        sheetStr = ""

        if data is None:
            return sheetStr

        # Header
        sheetStr += "**[%s](%s)**: %s  \n" % (
                data.pop('key', ""),
                data.pop('jiraurl', ""),
                data.pop('summary', ""),
                )
        # Fields
        for name, value in data.items():
            sheetStr+= "**%s**: " % name.capitalize()
            if len(value) > 80 or value.find('\n') != -1:
                sheetStr += ' \n'
            sheetStr += str(value) + '  \n'

        return sheetStr

    def close(self):
        self._fileRead.close()
        if self._fileTemp != None:
            self._fileTemp.close()

    def save(self):
        ret = True
        debug("Saving %s" % self._realName)
        try:
            self._fileRead.close()
            shutil.copyfile(self._fileTemp.name, self._realName)
            self._fileRead = open(self._realName)
        except Exception as inst:
            debug("Failed to replace/create %s: %s" % (self._realName, inst))
            ret = False
        return ret

    def openTemplate():
        templatePath = os.path.dirname(__file__) + "/sheet.template"
        sheetFile = None
        try:
            sheetFile = open(templatePath, 'r')
        except Exception as inst:
            debug("Unable to open template %s: %s" % (templatePath, inst))

        return sheetFile

    def _copy(self):
        try:
            self._fileRead.seek(0)
            self._fileTemp.write(self._fileRead.read())
            self._fileTemp.flush()
        except Exception as inst:
            debug("Failed to copy content of %s in %s: %s"
                    % (self._fileRead.name, self._fileTemp.name, inst))
            return False
        return True

    def _parseHeader(self, line):
        p = re.compile('^# ([A-Z]+-[0-9]+)[ ]*:[ ]*([^ ].*[^ ])[ ]* #$')
        key = ""
        summary = ""

        search = p.search(line)
        if search:
            key = search.group(1)
            summary = search.group(2)

        return key, summary

    def _parseField(self, line):
        pField = re.compile('^## [ ]*([^ ]+)[ ]* ##$')
        fieldName = ""

        search = pField.search(line)
        if search:
            fieldName = search.group(1)

        return fieldName

    def _parseComment(self, line):
        pComment = re.compile('^#([^#]*)')
        comment = ""

        search = pComment.search(line)
        if search:
            comment = search.group(1).strip(' ')

        return comment

    def _getValue(self, line, nextLine):
        pStop = re.compile('^#{1,2}([^#]+|$)')
        val = ""
        if not nextLine.startswith('#'):
            line = nextLine
            isStop = False
            for nextLine in self._fileRead:
                if pStop.match(nextLine) and line == '\n':
                    isStop = True
                    break
                val += line
                line = nextLine

            # Check if end of file
            if not isStop and line != '\n':
                val += line

        if val and val[-1] == '\n':
            val = val[:-1]

        return val, line, nextLine

    def _writeData2Sheet(self, data):
        ret = True
        try:
            # Write header
            self._fileTemp.write("# %s : %s #\n\n"
                    % (data.pop('key'), data.pop('summary')))

            # Write field and comments
            for key, value in data.items():
                if key.startswith('sheetComment'):
                    self._fileTemp.write("#%s" % value)
                else:
                    self._fileTemp.write("## %s ##\n" % key.capitalize())
                    self._fileTemp.write(value+"\n\n")

            self._fileTemp.flush()

        except Exception as inst:
            debug("Unable to write at sheet %s (%s): %s"
                    % (self._key, self._fileTemp.name, inst))
            ret = False

        return ret

    def __del__(self):
        self.close();


if __name__ == "__main__":
    conf = config()

    act = action(conf)
    args = parseArgs()
    act.runAction(args)

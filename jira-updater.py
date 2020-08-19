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
            "trackState",
            "jiraURL",
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
    mailParse.add_argument("outFile", type=argparse.FileType('w'),
            help="Output file")
    # Edit sheet
    editParser = subParsers.add_parser('edit',
            help="Edit jira ticket sheet")
    editParser.add_argument("key",
            help="Ticket key of the sheet")
    editParser.add_argument( "-d", "--sheetDir",
            help="Directory where is store ticket sheets")
    editParser.add_argument( "-n", "--no-update", action='store_true',
            help="Do not update sheet with field in csv")

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
            return func(self, args)
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

        try:
            csvOut.writeheader()
        except Exception as inst:
            debug("Fail to write csv header: %s" % inst)
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
        self._files['in'].close()
        self._files['out'].flush()

        if not args.outFile:
            shutil.copyfile(self._files['in'].name,
                    self._files['in'].name + '.old')
            shutil.copyfile(self._files['out'].name, self._files['in'].name)

        self._files['out'].close()

        # Report
        debug("\nNumber of updated rows: %d/%d," % (len(updatedKeys), rowNbr-1))
        debug(" " + self._jira.link(updatedKeys))
        debug("Number of new rows: %d/%d," % (len(newKeys), rowNbr-1))
        debug(" " + self._jira.link(newKeys))

    def edit(self, args):
        csvIn = self._initCsvReader(args.inFile)
        if csvIn == None:
            return False

        key = args.key
        if not self._checkKeyFormat(key):
            debug("Invalid key id: %s" % key)
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

        # Open temp sheet
        sheet2Edit = sheetObj.open(key, sheetDir, template=True)
        if sheet2Edit == None:
            return False

        for rowIn in csvIn:
            if rowIn['key'] == key:
                break

        if rowIn['key'] != key:
            debug("Ticket key \"%s\" not found in %s" % (key, args.inFile.name))
            return False

        outFields = conf.mergeFields(csvIn.fieldnames)
        rowOut = self._initFields(rowIn, outFields)

        sheet2Edit.initWrite(rowOut, update=(not args.no_update))

        # Open with editor
        editor = 'vim'
        if 'EDITOR' in os.environ:
            editor = os.environ['EDITOR']

        ret = os.system(editor + " '" + sheet2Edit.name(temp=True) + "'")

        if ret == 0:
            sheet2Edit.save()

        sheet2Edit.close()

    def search(self, args):
        print("search")

    def mail(self, args):
        print("mail")

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

        if not rowOut['jiraURL']:
            rowOut['jiraURL'] = conf.jiraURLRoot + '/' + rowOut['key']
        if not rowOut['trackState']:
            rowOut['trackState'] = 'New'
        if not rowOut['interest']:
            rowOut['interest'] = '0'
        
        return rowOut
    
    def _checkKeyFormat(self, key):
        p = re.compile('^[ \t]*[A-Z]+-[0-9]+[ \t]*$')
        return p.match(key)

    def _convertCvsDate(self, row):
        # Convert dates
        for i in self._conf.dateFields:
            if row[i]:
                row[i] = dateCSV.fromCsv(row[i])

    def _initCsvWriter(self, filePath, fields):
        try:
            if not filePath:
                updateOutPrefix = os.path.basename(__file__) + '.out.'
                self._files['out'] = tempfile.NamedTemporaryFile(mode='x',
                        prefix=updateOutPrefix, suffix=".csv")
            else:
                self._files['out'] = open(filePath, 'w')

            csvOut = csv.DictWriter(self._files['out'], fields,
                    quoting=csv.QUOTE_NONNUMERIC)
        except Exception as inst:
            debug("Fail to create CSV output file: %s" % inst)
            return None

        return csvOut

    def _initCsvReader(self, fdIn):
        self._files['in'] = fdIn
        try:
            csvIn = csv.DictReader(fdIn)
        except Exception as inst:
            debug("Fail to open CSV input file: %s" % inst)
            return None

        return csvIn

    funcs = {
            "update" : update,
            "search" : search,
            "mail"   : mail,
            "edit"   : edit,
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

            elif (row['trackState'] in ['Follow', 'Updated']
                    and isinstance(row['updated'], dateCSV)):
                date = dateCSV(row['updated'].date + timedelta(0,60))
                cmd = self._UpdatedJQL % (row['key'], date)
                issueArr = self._jiraApi.search_issues( cmd, maxResults=1,
                        fields=fields);
        except Exception as inst:
            debug('JIRA request fail (cmd="%s"): %s' % (cmd, inst))

        if len(issueArr) > 0:
            self._updateDict(issueArr[0], row)
            row['trackState'] = 'Updated'
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

    def link(self, issueIds):
        link = ''
        if len(issueIds) > 0:
            params = {
                    'maxResults' : 50000,
                    'jql' : 'key in (%s)' % ','.join(issueIds)
                    }
            link = (self._conf.jiraURLRoot
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
        except Exception as inst:
            debug("No existing file found for %s" % keyId)
            if template:
                debug("Use template instead")
                sheetFile = sheetObj.openTemplate()
            else:
                debug("Error: %s" % inst)
                return sheet

        if sheetFile != None:
            sheet = sheetObj(sheetFile, keyId, realName)

        return sheet

    def name(self, temp=False):
        if temp:
            return self._fileTemp.name
        return self._realName

    def initWrite(self, fields, update=True):
        try:
            self._fileTemp = tempfile.NamedTemporaryFile(mode='x',
                    prefix=self._key+'out', suffix=".md")
        except Exception as inst:
            debug("Unable to open a temp sheet for %s: %s" % (self._key, inst))

        if update:
            self.update(fields)
        else:
            self._copy()

    def update(self, fields):
        sheetData = self.parse()

        if sheetData == None:
            return False

        for i in sheetData:
            if i in fields:
                if not i in ['key','summary']:
                    sheetData[i] = self._formatVal(fields[i])
                else:
                    sheetData[i] = fields[i].strip()

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
                    dataSheet[field.casefold()] = value

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

    def close(self):
        self._fileRead.close()
        if self._fileTemp != None:
            self._fileTemp.close()

    def save(self):
        debug("Saving %s" % self._realName)
        try:
            shutil.copyfile(self._fileTemp.name, self._realName)
        except Exception as inst:
            debug("Failed to replace/create %s: %s" % (self._realName, inst))

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
            for nextLine in self._fileRead:
                if pStop.match(nextLine):
                    if line != '\n':
                        val += line
                    break
                val += line
                line = nextLine

        return val, line, nextLine

    def _formatVal(self, val):
        val.replace('\r\n', ' ');
        val.replace('\n', ' ');

        return re.sub("(.{80})", "\\1\n", val, 0, re.DOTALL) + '\n'

    def _writeData2Sheet(self, data):
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
                    self._fileTemp.write(value+'\n')

            self._fileTemp.flush()

        except Exception as inst:
            debug("Unable to write at sheet %s (%s): %s"
                    % (self._key, self._fileTemp.name, inst))


if __name__ == "__main__":
    conf = config()

    act = action(conf)
    args = parseArgs()
    act.runAction(args)

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

    def __init__(self, conf, jira):
        self._conf = conf
        self._jira = jira

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
            p = re.compile('^[ \t]*[A-Z]+-[0-9]+[ \t]*$')
            if 'key' not in rowIn or not p.match(rowIn['key']):
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
            debug("Creation date of th last entry in the database: %s" % lastCreated)
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


    def search(self, args):
        print("search")

    def mail(self, args):
        print("mail")

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


if __name__ == "__main__":
    conf = config()
    try:
        jiraUp = jiraUpdate(conf)
    except Exception as inst:
        debug( "Fail to init JIRA API: %s" % inst)
        sys.exit(inst.args[0])

    act = action(conf, jiraUp)
    args = parseArgs()
    act.runAction(args)

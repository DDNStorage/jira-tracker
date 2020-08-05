#!/usr/bin/python3

import argparse
import csv
import sys
import os
import tempfile
import re
from datetime import datetime
from datetime import timezone
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
            "risks",
            "fix",
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

class dateCSV(datetime):
    _strCsvFormat = '%Y-%m-%d %H:%M'

    def __str__(self):
        return self.strftime(self._strCsvFormat)

    def fromJira(str2Conv):
        try:
            return dateCSV.strptime(str2Conv, '%Y-%m-%dT%H:%M:%S.%f%z')
        except:
            debug("Unable to convert '%s'" % str2Conv)

    def fromCsv(str2Conv):
        try:
            return dateCSV.strptime(str2Conv+'+0000', self._strCsvFormat+'%z')
        except:
            return str2Conv
        
        try:
            return dateCSV.strptime(str2Conv+'+0000',  '%m/%d/%Y %H:%M%z')
        except:
            return str2Conv
            debug("Unable to convert '%s'" % str2Conv)

class action():
    _conf = None
    _jira = None

    def __init__(self, conf, jira):
        self._conf = conf
        self._jira = jira

    def initParser(self, subParsers):
        # Update
        updateParse = subParsers.add_parser('update', help="Update Database")
        updateParse.add_argument( "-o", "--outFile", type=argparse.FileType('w'),
                help="CSV database out path")
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
        try:
            csvIn = csv.DictReader(args.inFile)
            if args.outFile == None:
                updateOutPrefix = os.path.basename(__file__) + '.out.'
                args.outFile = tempfile.NamedTemporaryFile(mode='x',
                        prefix=updateOutPrefix, suffix=".csv")

            outFields = conf.mergeFields(csvIn.fieldnames)
            csvOut = csv.DictWriter(args.outFile, outFields)
        except Exception as inst:
            debug(inst)
            return inst.args[0]

        csvOut.writeheader()

        # stat var
        rowNbr = 1
        updatedKey = list()
        newKey = list()
        lastCreated = dateCSV(1900,1,1, tzinfo=timezone.utc)
        
        for rowIn in csvIn:
            rowNbr+=1
            p = re.compile('[A-Z]+-[0-9]+')
            if 'key' not in rowIn or not p.match(rowIn['key']):
                debug("Invalid 'key' at %s:%d" % (args.inFile.name, rowNbr))
                continue

            rowOut = dict.fromkeys(outFields)
            self._initLocalFields(rowIn, rowOut)

            if rowOut['trackState'] in ['Follow', 'Updated'] and self._jira.updateRow(rowOut):
                updatedKey.append(rowOut['key'])
                debug("Row %d (%s) is updated" % (rowNbr, rowOut['key']))

            if isinstance(rowOut['created'], dateCSV):
                    lastCreated = max(lastCreated, rowOut['created'])
            csvOut.writerow(rowOut)
    
    def search(self, args):
        print("search")
   
    def mail(self, args):
        print("mail")

    def _initLocalFields(self, rowIn, rowOut):
        rowOut.update({'trackState' : 'New', 'interest' : 0})
        rowOut.update(rowIn)
        if not rowOut['jiraURL']:
            rowOut['jiraURL']= conf.jiraURLRoot + '/' + rowOut['key']
        
        # Convert dates
        for i in self._conf.dateFields:
            if rowOut[i]:
                rowOut[i] = dateCSV.fromCsv(rowOut[i])
    
    funcs = {
            "update" : update,
            "search" : search,
            "mail"   : mail,
            }

class jiraUpdate():
    _conf = None
    _jiraApi = None
    _UpdateJQL = 'key = "%s" AND updated > "%s" '

    def __init__(self, conf):
        self._conf = conf
        self._jiraApi = JIRA(conf.jiraURLRoot)

    def updateRow(self, row, force=False):
        lu = None
        issueArr = list()
        ret = False
        cmd = None

        try:
            if not force and row['updated'] != None and row['updated'] != '':
                cmd = self._UpdateJQL % (row['key'], row['updated'])
                issueArr = self._jiraApi.search_issues( cmd, maxResults=1,
                        fields=','.join(self._conf.jiraFields));
            else:
                cmd = row['key']
                issueArr.append(self._jiraApi.issue( cmd,
                            fields=','.join(self._conf.jiraFields)));
        except Exception as inst:
            debug('JQL request fail (cmd="%s"): %s' % (cmd, inst))

        if len(issueArr) > 0:
            self._updateDict(issueArr[0], row)
            row['trackState'] = 'Updated'
            ret = True

        return ret
        
    def newLu(self, lastCreateDate):
        pass

    def _updateDict(self, jiraObj, dict2Up):
        fields = set(self._conf.jiraFields)
        fields.remove('key')

        for i in fields:
            dict2Up[i] = getattr(jiraObj.fields, i)

        # Convert dates
        for i in self._conf.dateFields:
            dict2Up[i] = dateCSV.fromJira(dict2Up[i])


conf = config()
try:
    jiraUp = jiraUpdate(conf)
except Exception as inst:
    debug( "Fail to init JIRA API: %s" % inst)
    sys.exit(inst.args[0])

act = action(conf, jiraUp)

#issue = jac.search_issues('project = LU AND updated > now()', fields=','.join(conf.jiraFields), maxResults=1)[0];
#print (issue.fields.status)
#for (field, value) in issue.raw['fields'].items():
#    print("%s=%s;" % (field, value))
#sys.exit(1)

# Parse arg
parser = argparse.ArgumentParser()
parser.add_argument("inFile", type=argparse.FileType('r'),
        help="CSV database path")
subParsers = parser.add_subparsers(dest='action',
        help="Action on CSV database")
act.initParser(subParsers)

args = parser.parse_args()

act.runAction(args)

#if args.output == None:
#    args.output = args.csvFile + ".out"
#
#try:
#    fdIn = open(args.csvFile);
#    csvIn = csv.DictReader(fdIn)
#except Exception as inst:
#    print(inst)
#    sys.exit(inst.args[0])
#
#try:
#    fdOut = open(args.output, 'x');
#    csvOut = csv.DictWriter(fdOut, csvIn.fieldnames)
#except Exception as inst:
#    print(inst)
#    sys.exit(inst.args[0])
#
#
#csvOut.writeheader()
#for row in csvIn:
#    print(row)
#    csvOut.writerow(row)

#!/usr/bin/env python
#
# FDSN-WS Dataselect prototype
#
# (c) 2014 Javier Quinteros, GEOFON team
# <javier@gfz-potsdam.de>
#
# ----------------------------------------------------------------------

"""Classes to access an indexed SDS structure to be used by the Dataselect-WS

(c) 2014 Javier Quinteros, GEOFON, GFZ Potsdam

This program is free software; you can redistribute it and/or modify it
under the terms of the GNU General Public License as published by the
Free Software Foundation; either version 2, or (at your option) any later
version. For more information, see http://www.gnu.org/

"""
import os
import datetime
import fnmatch
from struct import pack, unpack
from seiscomp import mseedlite


class NoDataAvailable(Exception):
    def __init__(self, message):
        # Call the base class constructor with the parameters it needs
        Exception.__init__(self, message)
        # Now for your custom code...
        #self.Errors = Errors


class SDS(object):
    def __init__(self, sdsRoot):
        if isinstance(sdsRoot, basestring):
            self.sdsRoot = [sdsRoot]
        elif type(sdsRoot) == type(list()):
            self.sdsRoot = sdsRoot

    def _date2int(self, d):
        return d.year * 1000 + d.timetuple().tm_yday

    def _iterFiles(self, root, year, net, sta, loc, cha, start, endt):
        # Transform from date to int
        # F.i. 2000.123 -> 2000123
        auxStart = self._date2int(start)
        auxEnd = self._date2int(endt)

        for f in os.listdir('%s/%d/%s/%s/%s' % (root, year, net, sta, cha)):
            if not fnmatch.fnmatch(f, '%s.%s.%s.%s.D.%d.???'% (net, sta, loc, cha.split('.')[0], year)):
                continue

            # Take the last three chars and check the date
            try:
                jd = int(f[-3:])
                d = datetime.datetime(year, 1, 1) + datetime.timedelta(jd)
                if auxStart <= self._date2int(d) <= auxEnd:
                    yield '%s/%d/%s/%s/%s/%s' % (root, year, net, sta, cha, f)
            except:
                continue

    def _iterDirs(self, net, sta, loc, cha, start, endt):
        for r in self.sdsRoot:
            for y in range(start.year, endt.year + 1):
                if not os.path.isdir('%s/%d' % (r, y)):
                   continue

                # Check into the year to filter networks
                for n in next(os.walk('%s/%d' % (r, y)))[1]:
                    if not fnmatch.fnmatch(n, net):
                        continue

                    for s in next(os.walk('%s/%d/%s' % (r, y, n)))[1]:
                        if not fnmatch.fnmatch(s, sta):
                            continue

                        for c in next(os.walk('%s/%d/%s/%s' % (r, y, n, s)))[1]:
                            if not fnmatch.fnmatch(c, cha):
                                continue

                            # Now that I found the directory, check the files
                            self._iterFiles(n, s, loc, c, start, endt)

    def _iterStreams(self, net, sta, loc, cha, start, endt):
        #print 'net %s; sta %s; cha %s' % (net, sta, cha)
        resultSet = set()
        for r in self.sdsRoot:
            for y in range(start.year, endt.year + 1):
                if not os.path.isdir('%s/%d' % (r, y)):
                   continue
                #print '%d OK' % y

                # Check into the year to filter networks
                #print next(os.walk('%s/%d' % (r, y)))[1]
                for n in next(os.walk('%s/%d' % (r, y)))[1]:
                    #print '%s OK2' % n
                    if not fnmatch.fnmatch(n, net):
                        continue

                    for s in next(os.walk('%s/%d/%s' % (r, y, n)))[1]:
                        if not fnmatch.fnmatch(s, sta):
                            continue
                        #print '%s OK3' % s

                        for c in next(os.walk('%s/%d/%s/%s' % (r, y, n, s)))[1]:
                            if not fnmatch.fnmatch(c.split('.')[0], cha):
                                continue
                            #print '%s OK4' % c

                            # Now that I found the directory, check the files
                            for l in self._iterLoc(r, y, n, s, loc, c, start, endt):
                                c = c.split('.')[0]
                                if (n, s, l, c) not in resultSet:
                                    #print (n, s, l, c)
                                    yield (n, s, l, c)
                                    resultSet.add((n, s, l, c))

        raise StopIteration

    def _iterLoc(self, root, year, net, sta, loc, cha, start, endt):
        # Transform from date to int
        # F.i. 2000.123 -> 2000123
        auxStart = self._date2int(start)
        auxEnd = self._date2int(endt)

        locSet = set()
        for f in os.listdir('%s/%d/%s/%s/%s' % (root, year, net, sta, cha)):
            if not fnmatch.fnmatch(f, '%s.%s.%s.%s.D.%d.???' % (net, sta, loc, cha.split('.')[0], year)):
                continue

            # Take the last three chars and check the date
            # try:
            jd = int(f[-3:])
            d = datetime.datetime(year, 1, 1) + datetime.timedelta(jd)
            if auxStart <= self._date2int(d) <= auxEnd:
                # print cha, auxStart, self._date2int(d), auxEnd, 'Add "%s"' % f.split('.')[2]
                locSet.add(f.split('.')[2])
            # except:
            #     continue
        #print 'Locs: %d' % len(locSet)
        return locSet

    def _getMSName(self, reqDate, net, sta, loc, cha):
        loc = loc if loc != '--' else ''

        for root in self.sdsRoot:
            yield '%s/%d/%s/%s/%s.D/%s.%s.%s.%s.D.%d.%s' % \
                (root, reqDate.year, net, sta, cha, net, sta, loc, cha,
                 reqDate.year, reqDate.strftime('%j'))
        raise StopIteration

    def getRawBytes(self, startt, endt, net, sta, loc, cha):
        eoDay = datetime.datetime(startt.year, startt.month, startt.day)\
            + datetime.timedelta(days=1)
        while startt < endt:
            try:
                yield self.getDayRaw(startt, min(endt, eoDay), net, sta,
                                     loc, cha)
            except NoDataAvailable:
                pass
            except:
                raise

            startt = datetime.datetime(startt.year, startt.month, startt.day)\
                + datetime.timedelta(days=1)
            eoDay = startt + datetime.timedelta(days=1)
        raise StopIteration

    def __time2recno(self, msFile, reclen, timeStart, recStart, timeEnd, recEnd, searchTime):
        if searchTime <= timeStart:
            msFile.seek(recStart * reclen)
            rec = mseedlite.Record(msFile)
            return (recStart, rec.end_time)

        if searchTime >= timeEnd:
            msFile.seek(recEnd * reclen)
            rec = mseedlite.Record(msFile)
            return (recEnd, rec.end_time)

        t1 = timeStart
        r1 = recStart
        t2 = timeEnd
        r2 = recEnd
        rn = int(r1 + (r2 - r1) * (searchTime - t1).total_seconds() / (t2 - t1).total_seconds())

        if rn < recStart:
            rn = recStart

        if rn > recEnd:
            rn = recEnd

        while True:
            msFile.seek(rn * reclen)
            rec = mseedlite.Record(msFile)

            if rec.begin_time < searchTime:
                r1 = rn
                t1 = rec.begin_time

                if t1 == t2:
                    break

                rn = int(r1 + (r2 - r1) * (searchTime - t1).total_seconds() / (t2 - t1).total_seconds())

                if rn < recStart:
                    rn = recStart

                if rn > recEnd:
                    rn = recEnd

                if rn == r1:
                    break

            else:
                r2 = rn
                t2 = rec.begin_time

                if t1 == t2:
                    break

                rn = int(r2 - (r2 - r1) * (t2 - searchTime).total_seconds() / (t2 - t1).total_seconds())

                if rn < recStart:
                    rn = recStart

                if rn > recEnd:
                    rn = recEnd

                if rn == r2:
                    break

        return (rn, rec.end_time)

    def __getWaveformNoIndex(self, startt, endt, msFile):
        rec = mseedlite.Record(msFile)
        reclen = rec.size
        recStart = 0
        timeStart = rec.begin_time

        msFile.seek(-reclen, 2)
        rec = mseedlite.Record(msFile)
        recEnd = msFile.tell() / reclen - 1
        timeEnd = rec.begin_time

        if startt > endt:
            raise Exception("startt > endt")

        if timeStart > timeEnd:
            raise Exception("timeStart > timeEnd")

        (lower, et1) = self.__time2recno(msFile, reclen, timeStart, recStart, timeEnd, recEnd, startt)
        (upper, et2) = self.__time2recno(msFile, reclen, startt, lower, timeEnd, recEnd, endt)
        if et1 < startt:
            lower += 1

        if et2 < endt or upper < lower:
            upper += 1

        msFile.seek(lower * reclen)
        return msFile.read((upper - lower + 1) * reclen)

    def getDayRaw(self, startt, endt, net, sta, loc, cha):
        """Retrieve records from an SDS archive. The start and end dates must
         be in the same day for this test."""

        #if ((startt.year != endt.year) or (startt.month != endt.month) or
        #   (startt.day != endt.day)):
        #    msg = "Error in getDayRaw: only the time can differ between" + \
        #        " start and end dates."
        #    raise Exception(msg)

        # Take into account the case of empty location
        if loc == '--':
            loc = ''

        # For every file that contains information to be retrieved
        try:
            # Check that the data file exists
            for dataFile in self._getMSName(startt, net, sta, loc, cha):
                #print dataFile
                if not os.path.exists(dataFile):
                    continue

                #print 'Try %s on %s' % (dataFile, startt)
                with open(dataFile, 'rb') as msFile:
                    return self.__getWaveformNoIndex(startt, endt, msFile)
            else:
                raise NoDataAvailable('Error: No data for %s on %d/%d/%d!' %
                                      ((net, sta, loc, cha), startt.year,
                                       startt.month, startt.day))
        except:
            raise

    # def _buildPath(self, startD, net, sta, loc, cha):
    #     relPath = os.path.join(str(startD.year), net, sta, cha + '.D')
    #     filename = '%s.%s.%s.%s.D.%d.%d' % (net, sta, loc, cha, startD.year,
    #                                         startD.timetuple().tm_yday)
    #     idxFileName = os.path.join(self.idxRoot, relPath,
    #                                '.%s.idx' % filename)
    #     return idxFileName
